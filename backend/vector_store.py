import json
import sqlite3
import math
import os
from typing import List, Dict, Any, Optional

class VectorStore:
    def __init__(self, db_path: str = "data/vector_store.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
        self._cache = {} # Map of document_id -> list of chunk dicts (including deserialized embeddings)
        self._load_cache()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Documents table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Chunks table (stores text and image chunks)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    page_num INTEGER NOT NULL,
                    chunk_type TEXT NOT NULL, -- 'text' or 'visual'
                    content TEXT NOT NULL,
                    image_path TEXT, -- path to visual chart crop or page image
                    embedding TEXT NOT NULL, -- JSON serialized float list
                    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def _load_cache(self):
        """Loads all chunks and deserializes their embeddings into an in-memory cache."""
        self._cache = {}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, document_id, page_num, chunk_type, content, image_path, embedding FROM chunks")
            rows = cursor.fetchall()
            
            for row in rows:
                doc_id = row["document_id"]
                if doc_id not in self._cache:
                    self._cache[doc_id] = []
                
                # Pre-deserialize embedding
                try:
                    embedding = json.loads(row["embedding"])
                except Exception:
                    embedding = []
                    
                self._cache[doc_id].append({
                    "id": row["id"],
                    "document_id": doc_id,
                    "page_num": row["page_num"],
                    "chunk_type": row["chunk_type"],
                    "content": row["content"],
                    "image_path": row["image_path"],
                    "embedding": embedding
                })

    def add_document(self, doc_id: str, filename: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO documents (id, filename) VALUES (?, ?)",
                (doc_id, filename)
            )
            conn.commit()

    def delete_document(self, doc_id: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
            cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()
            
        # Update cache
        if doc_id in self._cache:
            del self._cache[doc_id]

    def add_chunks(self, chunks: List[Dict[str, Any]]):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for chunk in chunks:
                cursor.execute(
                    """
                    INSERT INTO chunks (id, document_id, page_num, chunk_type, content, image_path, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["id"],
                        chunk["document_id"],
                        chunk["page_num"],
                        chunk["chunk_type"],
                        chunk["content"],
                        chunk.get("image_path"),
                        json.dumps(chunk["embedding"])
                    )
                )
            conn.commit()
            
        # Update cache
        for chunk in chunks:
            doc_id = chunk["document_id"]
            if doc_id not in self._cache:
                self._cache[doc_id] = []
            self._cache[doc_id].append({
                "id": chunk["id"],
                "document_id": chunk["document_id"],
                "page_num": chunk["page_num"],
                "chunk_type": chunk["chunk_type"],
                "content": chunk["content"],
                "image_path": chunk.get("image_path"),
                "embedding": chunk["embedding"]
            })

    def list_documents(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT d.id, d.filename, d.uploaded_at, COALESCE(MAX(c.page_num), 0) as pages
                FROM documents d
                LEFT JOIN chunks c ON d.id = c.document_id
                GROUP BY d.id
                ORDER BY d.uploaded_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_document_chunks(self, document_id: str) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, document_id, page_num, chunk_type, content, image_path FROM chunks WHERE document_id = ?",
                (document_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def search(self, query_embedding: List[float], document_id: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        # Retrieve candidate chunks from cache
        candidates = []
        if document_id:
            candidates = self._cache.get(document_id, [])
        else:
            for doc_chunks in self._cache.values():
                candidates.extend(doc_chunks)
                
        # If cache is empty and it shouldn't be, reload cache from DB just in case
        if not candidates and not self._cache:
            self._load_cache()
            if document_id:
                candidates = self._cache.get(document_id, [])
            else:
                for doc_chunks in self._cache.values():
                    candidates.extend(doc_chunks)
                    
        results = []
        for chunk in candidates:
            similarity = self._cosine_similarity(query_embedding, chunk["embedding"])
            
            results.append({
                "id": chunk["id"],
                "document_id": chunk["document_id"],
                "page_num": chunk["page_num"],
                "chunk_type": chunk["chunk_type"],
                "content": chunk["content"],
                "image_path": chunk["image_path"],
                "similarity": similarity
            })
            
        # Sort by similarity descending
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _dot_product(v1: List[float], v2: List[float]) -> float:
        return sum(x * y for x, y in zip(v1, v2))

    @staticmethod
    def _magnitude(v: List[float]) -> float:
        return math.sqrt(sum(x * x for x in v))

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        mag1 = self._magnitude(v1)
        mag2 = self._magnitude(v2)
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return self._dot_product(v1, v2) / (mag1 * mag2)
