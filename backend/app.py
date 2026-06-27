import os
import shutil
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List

from backend.config import Config
from backend.vector_store import VectorStore
from backend.document_processor import DocumentProcessor

# Initialize FastAPI
app = FastAPI(title="Multimodal RAG: Chart & Document Analyzer")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup directories
Config.setup_dirs()

# Initialize database and processor
db = VectorStore()
processor = DocumentProcessor()

# Serve data directory for images and uploaded PDFs
app.mount("/data", StaticFiles(directory="data"), name="data")
# Serve frontend assets from /frontend folder
app.mount("/static", StaticFiles(directory="frontend"), name="frontend")

class ConfigUpdate(BaseModel):
    api_key: str

class QueryRequest(BaseModel):
    query: str
    document_id: Optional[str] = None
    top_k: int = 5

@app.on_event("startup")
def startup_event():
    Config.setup_dirs()
    if Config.GEMINI_API_KEY:
        processor.set_api_key(Config.GEMINI_API_KEY)

@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")

@app.get("/api/config")
def get_config():
    return {
        "has_api_key": bool(processor.api_key)
    }

@app.post("/api/config")
def update_config(config: ConfigUpdate):
    if not config.api_key.strip():
        raise HTTPException(status_code=400, detail="API Key cannot be empty.")
    processor.set_api_key(config.api_key.strip())
    Config.save_api_key(config.api_key.strip())
    return {"status": "success", "message": "API key updated successfully"}

@app.get("/api/documents")
def list_documents():
    return db.list_documents()

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    doc_id = str(uuid.uuid4())
    filename = file.filename
    pdf_path = os.path.join(Config.UPLOADS_DIR, f"{doc_id}.pdf")
    
    # Save the file
    try:
        with open(pdf_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    # Process PDF (extract text + render pages + run VLM for visual elements)
    try:
        chunks, page_count = processor.process_pdf(pdf_path, doc_id)
        
        # Save to database
        db.add_document(doc_id, filename)
        db.add_chunks(chunks)
        
        return {
            "status": "success",
            "document_id": doc_id,
            "filename": filename,
            "pages": page_count,
            "chunks_count": len(chunks)
        }
    except Exception as e:
        # Clean up files in case of error
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        shutil.rmtree(os.path.join(Config.IMAGES_DIR, doc_id), ignore_errors=True)
        db.delete_document(doc_id)
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    pdf_path = os.path.join(Config.UPLOADS_DIR, f"{doc_id}.pdf")
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    
    images_dir = os.path.join(Config.IMAGES_DIR, doc_id)
    if os.path.exists(images_dir):
        shutil.rmtree(images_dir)
        
    db.delete_document(doc_id)
    return {"status": "success", "message": f"Document {doc_id} deleted successfully"}

@app.get("/api/documents/{doc_id}/suggested-questions")
def get_suggested_questions(doc_id: str):
    chunks = db.get_document_chunks(doc_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="Document not found or has no content.")
    questions = processor.generate_suggested_questions(chunks)
    return {"questions": questions}

@app.post("/api/chat")
def chat(request: QueryRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
        
    # Step 1: Embed query
    try:
        query_embedding = processor._get_embedding(request.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to embed query: {str(e)}")
        
    # Step 2: Retrieve similar chunks
    retrieved_chunks = db.search(
        query_embedding=query_embedding,
        document_id=request.document_id,
        top_k=request.top_k
    )
    
    if not retrieved_chunks:
        return {
            "answer": "No relevant content found in the database. Please upload a document first.",
            "sources": []
        }
        
    # Step 3: Generate answer using VLM/LLM
    answer = processor.answer_query(request.query, retrieved_chunks)
    
    # Format and return sources alongside the answer
    sources = []
    for chunk in retrieved_chunks:
        sources.append({
            "document_id": chunk["document_id"],
            "page_num": chunk["page_num"],
            "chunk_type": chunk["chunk_type"],
            "content": chunk["content"],
            "image_path": chunk["image_path"],
            "similarity": chunk["similarity"]
        })
        
    return {
        "answer": answer,
        "sources": sources
    }
