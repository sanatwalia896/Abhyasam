

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, List, Optional
import os
import json
import logging
import time
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict, List, Optional
import os
import json
import logging
import time
from chatbot import AbhyasamChat
from notion_loader import NotionPageLoader
from populate_vectors import AbhyasamRAG
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Abhyasam",
    description="A professional revision tool for Notion notes with quiz and Q&A modes.",
    version="1.0.0"
)
# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*" ],  # Allow your frontend origin
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Initialize chatbot
chatbot = AbhyasamChat(model_name="openai/gpt-oss-120b")

# Pydantic models for request validation (keep as is)
class AskRequest(BaseModel):
    question: str
    session_id: str = "student1"
    page_title: Optional[str] = None

class QuizRequest(BaseModel):
    topic_query: str = "key concepts"
    num_batches: int = 3
    questions_per_batch: int = 10
    page_title: Optional[str] = None

class StartQuizRequest(BaseModel):
    num_questions: int
    session_id: str = "student1"
    page_title: Optional[str] = None

class SubmitAnswerRequest(BaseModel):
    answer: str
    session_id: str = "student1"

# Create data directory if it doesn't exist
os.makedirs("data", exist_ok=True)

# Refresh Notion pages and update vector store
@app.post("/api/refresh-notion")
async def refresh_notion(force: bool = False):
    """Sync Notion pages, update vector store, and save page titles."""
    try:
        loader = NotionPageLoader(os.getenv("NOTION_TOKEN"))
        page_ids = loader.search_all_pages()
        pages = []
        title_map = []
        for page_id in page_ids:
            title = loader.get_page_title(page_id)
            blocks = loader.get_page_blocks(page_id)
            content = "\n".join([b["text"] for b in blocks if b.get("text")])
            pages.append({"title": title, "content": content, "page_id": page_id})
            title_map.append({"page_id": page_id, "title": title})
        
        # Save page titles to JSON in data/
        with open("data/page_id_with_titles.json", "w") as f:
            json.dump(title_map, f, indent=2)
        
        # Upsert to Pinecone (keep as is)
        rag = AbhyasamRAG(api_key=os.getenv("PINECONE_API_KEY"))
        all_docs = []
        from langchain_core.documents import Document
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        for page in pages:
            doc = Document(
                page_content=page["content"],
                metadata={"source": "Notion", "page_title": page["title"], "page_id": page["page_id"]}
            )
            all_docs.extend(splitter.split_documents([doc]))
        
        rag.upsert_documents(all_docs, namespace="notion-knowledge")
        return JSONResponse({
            "status": "success",
            "pages_updated": len(pages),
            "message": "Notion pages successfully synced and vector store updated"
        })
    except Exception as e:
        logger.error(f"Error refreshing Notion: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync Notion pages: {str(e)}")

# Fetch Notion pages for dropdown
@app.get("/api/notion-pages")
async def fetch_notion_pages():
    """Return list of Notion page titles and IDs for dropdown."""
    try:
        with open("data/page_id_with_titles.json", "r") as f:
            pages = json.load(f)
        return JSONResponse({
            "status": "success",
            "pages": pages,
            "message": "Notion pages retrieved successfully"
        })
    except FileNotFoundError:
        logger.warning("page_id_with_titles.json not found; fetching from Notion")
        try:
            loader = NotionPageLoader(os.getenv("NOTION_TOKEN"))
            page_ids = loader.search_all_pages()
            pages = [{"page_id": pid, "title": loader.get_page_title(pid)} for pid in page_ids]
            with open("data/page_id_with_titles.json", "w") as f:
                json.dump(pages, f, indent=2)
            return JSONResponse({
                "status": "success",
                "pages": pages,
                "message": "Notion pages retrieved and cached successfully"
            })
        except Exception as e:
            logger.error(f"Error fetching Notion pages: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve Notion pages")
    except Exception as e:
        logger.error(f"Error reading page_id_with_titles.json: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve Notion pages")

# Chat endpoint (keep as is)
@app.post("/api/chat")
async def chat(req: AskRequest):
    try:
        if not req.question.strip():
            raise HTTPException(status_code=400, detail="Question cannot be empty")
        response = chatbot.ask_question(req.question, req.session_id, req.page_title)
        return JSONResponse({
            "status": "success",
            "answer": response["answer"],
            "page_title": req.page_title or "All pages"
        })
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process question: {str(e)}")

# Start interactive quiz endpoint (keep as is)
@app.post("/api/start-quiz")
async def start_quiz(req: StartQuizRequest):
    try:
        if req.num_questions < 1:
            raise HTTPException(status_code=400, detail="Number of questions must be at least 1")
        response = chatbot.start_interactive_quiz(req.session_id, req.num_questions, req.page_title)
        return JSONResponse(response)
    except Exception as e:
        logger.error(f"Error starting quiz: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start quiz: {str(e)}")

# Submit quiz answer endpoint (keep as is)
@app.post("/api/submit-quiz-answer")
async def submit_quiz_answer(req: SubmitAnswerRequest):
    try:
        if not req.answer.strip():
            raise HTTPException(status_code=400, detail="Answer cannot be empty")
        response = chatbot.submit_quiz_answer(req.session_id, req.answer)
        return JSONResponse(response)
    except Exception as e:
        logger.error(f"Error submitting quiz answer: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit answer: {str(e)}")

# Generate quiz endpoint
@app.post("/api/generate-quiz")
async def generate_quiz(req: QuizRequest):
    """Generate a new MCQ quiz for a specific page and overwrite questions.json."""
    try:
        if req.num_batches < 1 or req.questions_per_batch < 1:
            raise HTTPException(status_code=400, detail="Invalid quiz parameters")
        
        start_time = time.time()
        questions = chatbot.generate_quiz(
            topic_query=req.topic_query,
            num_batches=req.num_batches,
            questions_per_batch=req.questions_per_batch,
            page_title=req.page_title
        )
        
        if not questions:
            raise HTTPException(status_code=500, detail="No questions generated. Ensure Notion pages are synced.")
        
        # Format questions for quiz.js
        formatted_questions = [
            {
                "question": q["question"],
                "options": [q["options"]["A"], q["options"]["B"], q["options"]["C"], q["options"]["D"]],
                "answer": ord(q["answer"]) - ord("A")  # Convert A=0, B=1, etc.
            }
            for q in questions
        ]
        
        # Overwrite data/questions.json
        with open("data/questions.json", "w") as f:
            json.dump(formatted_questions, f, indent=2)
        
        generation_time = time.time() - start_time
        return JSONResponse({
            "status": "success",
            "questions_count": len(formatted_questions),
            "page_title": req.page_title or "All pages",
            "generation_time": round(generation_time, 2),
            "message": f"Generated {len(formatted_questions)} questions for {req.page_title or 'all pages'}"
        })
    except Exception as e:
        logger.error(f"Error generating quiz: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate quiz: {str(e)}")

# New endpoint: Get questions (for frontend to fetch)
@app.get("/api/questions")
async def get_questions():
    """Return the generated questions.json."""
    try:
        with open("data/questions.json", "r") as f:
            questions = json.load(f)
        return JSONResponse({
            "status": "success",
            "questions": questions
        })
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Questions not generated yet. Run /api/generate-quiz first.")
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve questions")

# Health check endpoint (keep as is)
@app.get("/api/health")
async def health_check():
    try:
        # Test Pinecone connection
        rag = AbhyasamRAG(api_key=os.getenv("PINECONE_API_KEY"))
        index = rag.pc.Index("abhyasam-index")
        index.describe_index_stats()
        
        # Test Notion connection
        loader = NotionPageLoader(os.getenv("NOTION_TOKEN"))
        loader.search_all_pages()
        
        return JSONResponse({
            "status": "success",
            "message": "Abhyasam is healthy",
            "components": {
                "fastapi": "running",
                "pinecone": "connected",
                "notion": "connected",
                "groq": "initialized"
            }
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable: One or more components are down")

# API documentation (Swagger) is automatic at /docs