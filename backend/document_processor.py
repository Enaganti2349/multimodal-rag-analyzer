import os
import uuid
import fitz  # PyMuPDF
from PIL import Image
import google.generativeai as genai
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
from backend.config import Config

class DocumentProcessor:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or Config.GEMINI_API_KEY
        if self.api_key:
            genai.configure(api_key=self.api_key)

    def set_api_key(self, api_key: str):
        self.api_key = api_key
        genai.configure(api_key=api_key)

    def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding using Google's gemini-embedding-001 model, with a fallback if API key is invalid."""
        if not self.api_key:
            # Fallback mock embedding (3072 dimensions) for offline/demo use
            h = hash(text)
            return [((h + i) % 1000) / 1000.0 for i in range(3072)]
        try:
            response = genai.embed_content(
                model="models/gemini-embedding-001",
                content=text,
                task_type="retrieval_document"
            )
            return response['embedding']
        except Exception as e:
            print(f"Error generating embedding: {e}. Falling back to mock embedding.")
            h = hash(text)
            return [((h + i) % 1000) / 1000.0 for i in range(3072)]

    def _get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings in batch with a fallback if API key is invalid."""
        if not self.api_key:
            return [self._get_embedding(t) for t in texts]
        
        # Chunk texts into batches of 100 to prevent API limit issues
        batch_size = 100
        embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                response = genai.embed_content(
                    model="models/gemini-embedding-001",
                    content=batch,
                    task_type="retrieval_document"
                )
                embeddings.extend(response['embedding'])
            except Exception as e:
                print(f"Error generating batched embeddings: {e}. Falling back to individual generation.")
                # Fallback for this batch
                for text in batch:
                    embeddings.append(self._get_embedding(text))
                    
        return embeddings

    def chunk_text(self, text: str, chunk_size: int = 800, overlap: int = 200) -> List[str]:
        chunks = []
        if not text:
            return chunks
        
        # Split into paragraphs
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 <= chunk_size:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # If paragraph itself is too large, split it by characters
                if len(para) > chunk_size:
                    start = 0
                    while start < len(para):
                        end = min(start + chunk_size, len(para))
                        chunks.append(para[start:end])
                        start += chunk_size - overlap
                    current_chunk = ""
                else:
                    current_chunk = para
                    
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    def process_pdf(self, pdf_path: str, doc_id: str) -> Tuple[List[Dict[str, Any]], int]:
        """
        Parses PDF page-by-page.
        1. Extracts text and chunks it.
        2. Renders each page as an image.
        3. Uses VLM (Gemini) in parallel to describe charts or transcribe scanned pages (OCR).
        4. Embeds all content in batches.
        Returns a list of chunks ready to be written to the vector database and the page count.
        """
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        raw_chunks = []
        pages_to_vlm = []

        # Setup folders
        doc_images_dir = os.path.join(Config.IMAGES_DIR, doc_id)
        os.makedirs(doc_images_dir, exist_ok=True)

        for page_num in range(page_count):
            page = doc.load_page(page_num)
            
            # 1. Extract text and create text chunks
            text = page.get_text()
            text_chunks = self.chunk_text(text)
            
            # Add text chunks (without embedding first)
            for i, chunk_text in enumerate(text_chunks):
                chunk_id = f"{doc_id}_p{page_num}_t{i}"
                raw_chunks.append({
                    "id": chunk_id,
                    "document_id": doc_id,
                    "page_num": page_num + 1,  # 1-indexed for users
                    "chunk_type": "text",
                    "content": chunk_text,
                    "image_path": None
                })

            # Render page as image (required for standard page display in frontend too)
            pix = page.get_pixmap(dpi=150)
            image_name = f"page_{page_num + 1}.png"
            page_image_path = os.path.join(doc_images_dir, image_name)
            pix.save(page_image_path)
            relative_image_path = f"data/extracted_images/{doc_id}/{image_name}"

            # 2. Smart Skip check: check if page has visuals OR if it's scanned (empty/short text)
            has_images = len(page.get_images()) > 0
            has_drawings = len(page.get_drawings()) > 0
            is_scanned = len(text.strip()) < 50
            
            if has_images or has_drawings or is_scanned:
                # Add to parallel VLM queue, passing is_scanned flag
                pages_to_vlm.append((page_num + 1, page_image_path, relative_image_path, is_scanned))

        doc.close()

        # 3. Parallel VLM Generation
        visual_summaries = {}
        if pages_to_vlm:
            max_workers = min(len(pages_to_vlm), 5)  # Limit concurrent calls to stay within API rate limit
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._get_visual_summary, img_path, page_num, is_scanned): (page_num, rel_path)
                    for page_num, img_path, rel_path, is_scanned in pages_to_vlm
                }
                for future in futures:
                    page_num, rel_path = futures[future]
                    try:
                        summary = future.result()
                        if summary and "No visual charts or diagrams" not in summary:
                            visual_summaries[page_num] = (summary, rel_path)
                    except Exception as e:
                        print(f"Error in parallel VLM processing for page {page_num}: {e}")

        # Assemble visual/OCR chunks (without embedding first)
        for page_num, (summary, rel_path) in visual_summaries.items():
            chunk_id = f"{doc_id}_p{page_num - 1}_v"
            raw_chunks.append({
                "id": chunk_id,
                "document_id": doc_id,
                "page_num": page_num,
                "chunk_type": "visual",
                "content": summary,
                "image_path": rel_path
            })

        # 4. Batched Embedding Generation
        if raw_chunks:
            contents = [c["content"] for c in raw_chunks]
            embeddings = self._get_embeddings_batch(contents)
            for chunk, embedding in zip(raw_chunks, embeddings):
                chunk["embedding"] = embedding

        return raw_chunks, page_count

    def _get_visual_summary(self, image_path: str, page_num: int, is_scanned: bool = False) -> str:
        """Sends the page image to Gemini VLM to check for and summarize charts/diagrams, or transcribe scanned text."""
        if not self.api_key:
            # Mock mode if no key is provided
            print(f"Skipping VLM step for page {page_num} (no API Key).")
            return "No visual charts or diagrams on this page."
            
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            image = Image.open(image_path)
            
            if is_scanned:
                prompt = """
                Analyze the provided image of a document page. This page appears to be a scanned document or an image-only page.
                Please perform OCR and transcribe ALL text on this page accurately, preserving paragraphs and headers.
                If there are also any charts, graphs, tables, or diagrams on this page, describe them in detail at the end of your response, and transcribe any tables in markdown format.
                """
            else:
                prompt = """
                Analyze the provided image of a document page.
                Identify if there are any visual elements like charts, graphs, tables, flowcharts, timelines, maps, schemas, or diagrams on this page.
                If there are, provide a detailed textual description of each visual element, including:
                1. The type of visual element (e.g., line chart, bar graph, pie chart, structured comparison table, architecture diagram).
                2. The main titles, section headers, axis labels, legends, or key labels.
                3. Key trends, specific data points, percentages, or relationships shown in the visual.
                4. A clear summary of the core message or insight the visual element conveys.
                
                If the page contains ONLY paragraphs of standard text (no charts, graphs, diagrams, maps, or structured tables), reply with exactly this sentence:
                "No visual charts or diagrams on this page."
                
                Be precise and quantitative. Avoid vague descriptions. If there is a table, transcribe its rows and columns in markdown table format.
                """
            
            response = model.generate_content([prompt, image])
            return response.text.strip()
        except Exception as e:
            print(f"Error calling VLM for page {page_num}: {e}")
            return "No visual charts or diagrams on this page."

    def generate_suggested_questions(self, chunks: List[Dict[str, Any]]) -> List[str]:
        """Generate suggested questions based on the retrieved chunks from a document."""
        if not self.api_key:
            return [
                "What is the main topic of this document?",
                "Are there any charts or tables on the pages?",
                "Provide a summary of the document's key points."
            ]
            
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # Combine content of up to 5 visual summaries and 5 text chunks to give a good overview
            visual_contents = [c["content"] for c in chunks if c["chunk_type"] == "visual"][:5]
            text_contents = [c["content"] for c in chunks if c["chunk_type"] == "text"][:5]
            
            sample_context = "\n\n".join(visual_contents + text_contents)
            
            if not sample_context.strip():
                return [
                    "What is the main topic of this document?",
                    "Are there any charts or tables on the pages?",
                    "Provide a summary of the document's key points."
                ]
                
            prompt = f"""
            Analyze the following brief sample content from a document containing text and visual chart descriptions.
            Generate 3 interesting, specific, and quantitative questions that a user can ask to explore the charts, tables, or text of this document.
            Ensure the questions are diverse:
            - At least one question should ask about a specific trend, data point, or insight in a chart/graph/table mentioned.
            - The questions should be clear, concise, and direct (no meta-language).
            - Do not include numbering or markdown formatting in your response. Just return the questions separated by newlines.
            
            Sample Content:
            {sample_context[:4000]}
            
            Questions:
            """
            
            response = model.generate_content(prompt)
            questions = [q.strip() for q in response.text.strip().split("\n") if q.strip()]
            
            # Clean up formatting if any
            cleaned_questions = []
            for q in questions:
                # Remove leading numbers like "1. ", "2. ", "- "
                q_clean = q.lstrip("0123456789.-*• ")
                if q_clean:
                    cleaned_questions.append(q_clean)
                    
            return cleaned_questions[:3]
        except Exception as e:
            print(f"Error generating suggested questions: {e}")
            return [
                "What is the main topic of this document?",
                "Are there any charts or tables on the pages?",
                "Provide a summary of the document's key points."
            ]

    def answer_query(self, query: str, retrieved_chunks: List[Dict[str, Any]]) -> str:
        """Generate response based on retrieved chunks using Gemini."""
        if not self.api_key:
            # Fallback response if no API key is set
            sources = []
            for chunk in retrieved_chunks:
                sources.append(f"Page {chunk['page_num']} ({chunk['chunk_type']} chunk)")
            return (
                f"[DEMO MODE] This is a mock response because no Gemini API Key is configured.\n\n"
                f"Your query was: '{query}'\n\n"
                f"Most relevant sections found in the document:\n"
                + "\n".join([f"- {src}: {chunk['content'][:150]}..." for src, chunk in zip(sources, retrieved_chunks)]) +
                f"\n\nTo get actual answers generated from the document text and charts, please configure a Gemini API key in the top bar."
            )
            
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            # Format context
            context_items = []
            for chunk in retrieved_chunks:
                source_info = f"[Source: Page {chunk['page_num']}, Type: {chunk['chunk_type']}]"
                context_items.append(f"{source_info}\n{chunk['content']}")
            
            context = "\n\n---\n\n".join(context_items)
            
            prompt = f"""
            You are a helpful and intelligent Multimodal RAG Assistant. 
            You are analyzing documents containing text, tables, charts, and diagrams.
            
            Below is the context retrieved from the document corresponding to the user's question.
            Some sections of the context are plain text from the document, and others are detailed descriptions of visual elements (charts, graphs, tables) that were extracted and summarized by a Vision-Language Model.
            
            Please answer the user's question accurately using ONLY the provided context. If the answer cannot be found or inferred from the context, state that you don't have enough information.
            
            When referring to details from charts or diagrams, explicitly mention that they are from the visual/chart elements on the respective page.
            
            Context:
            {context}
            
            User Question:
            {query}
            
            Answer:
            """
            
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error generating answer: {str(e)}"
