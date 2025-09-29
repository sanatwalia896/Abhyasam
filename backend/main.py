from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import json
import logging
import time

# Local imports
from chatbot import AbhyasamChat
from notion_loader import NotionPageLoader
from populate_vectors import AbhyasamRAG

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Abhyasam",
    description="A professional revision tool for Notion notes with quiz and Q&A modes.",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this to your frontend domain for better security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize chatbot (lazy init to avoid Vercel cold start issues)
chatbot = AbhyasamChat(model_name="openai/gpt-oss-120b")

# ---------------------------
# Request Models
# ---------------------------

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

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

# ---------------------------
# API Endpoints
# ---------------------------

@app.get("/")
async def root():
    """Basic root endpoint to verify deployment."""
    return {"status": "ok", "message": "Welcome to Abhyasam API"}

@app.post("/api/refresh-notion")
async def refresh_notion(force: bool = False):
    try:
        loader = NotionPageLoader(os.getenv("NOTION_TOKEN"))
        page_ids = loader.search_all_pages()

        pages, title_map = [], []
        for page_id in page_ids:
            title = loader.get_page_title(page_id)
            blocks = loader.get_page_blocks(page_id)
            content = "\n".join([b["text"] for b in blocks if b.get("text")])
            pages.append({"title": title, "content": content, "page_id": page_id})
            title_map.append({"page_id": page_id, "title": title})

        with open("data/page_id_with_titles.json", "w") as f:
            json.dump(title_map, f, indent=2)

        rag = AbhyasamRAG(api_key=os.getenv("PINECONE_API_KEY"))
        from langchain_core.documents import Document
        from langchain.text_splitter import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        all_docs = []
        for page in pages:
            doc = Document(
                page_content=page["content"],
                metadata={"source": "Notion", "page_title": page["title"], "page_id": page["page_id"]}
            )
            all_docs.extend(splitter.split_documents([doc]))

        rag.upsert_documents(all_docs, namespace="notion-knowledge")
        return {"status": "success", "pages_updated": len(pages)}
    except Exception as e:
        logger.error(f"Error refreshing Notion: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync Notion pages: {str(e)}")

@app.get("/api/notion-pages")
async def fetch_notion_pages():
    try:
        with open("data/page_id_with_titles.json", "r") as f:
            pages = json.load(f)
        return {"status": "success", "pages": pages}
    except FileNotFoundError:
        return {"status": "empty", "pages": []}
    except Exception as e:
        logger.error(f"Error fetching Notion pages: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve Notion pages")

@app.post("/api/chat")
async def chat(req: AskRequest):
    try:
        if not req.question.strip():
            raise HTTPException(status_code=400, detail="Question cannot be empty")
        response = chatbot.ask_question(req.question, req.session_id, req.page_title)
        return {"status": "success", "answer": response["answer"], "page_title": req.page_title or "All pages"}
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process question: {str(e)}")

@app.post("/api/start-quiz")
async def start_quiz(req: StartQuizRequest):
    try:
        if req.num_questions < 1:
            raise HTTPException(status_code=400, detail="Number of questions must be at least 1")
        response = chatbot.start_interactive_quiz(req.session_id, req.num_questions, req.page_title)
        return response
    except Exception as e:
        logger.error(f"Error starting quiz: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start quiz: {str(e)}")

@app.post("/api/submit-quiz-answer")
async def submit_quiz_answer(req: SubmitAnswerRequest):
    try:
        if not req.answer.strip():
            raise HTTPException(status_code=400, detail="Answer cannot be empty")
        return chatbot.submit_quiz_answer(req.session_id, req.answer)
    except Exception as e:
        logger.error(f"Error submitting quiz answer: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit answer: {str(e)}")

@app.post("/api/generate-quiz")
async def generate_quiz(req: QuizRequest):
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

        formatted_questions = [
            {
                "question": q["question"],
                "options": [q["options"]["A"], q["options"]["B"], q["options"]["C"], q["options"]["D"]],
                "answer": ord(q["answer"]) - ord("A")
            }
            for q in questions
        ]

        with open("data/questions.json", "w") as f:
            json.dump(formatted_questions, f, indent=2)

        generation_time = round(time.time() - start_time, 2)
        return {
            "status": "success",
            "questions_count": len(formatted_questions),
            "page_title": req.page_title or "All pages",
            "generation_time": generation_time
        }
    except Exception as e:
        logger.error(f"Error generating quiz: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate quiz: {str(e)}")

@app.get("/api/questions")
async def get_questions():
    try:
        with open("data/questions.json", "r") as f:
            questions = json.load(f)
        return {"status": "success", "questions": questions}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Questions not generated yet.")
    except Exception as e:
        logger.error(f"Error fetching questions: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve questions")

@app.get("/api/health")
async def health_check():
    try:
        rag = AbhyasamRAG(api_key=os.getenv("PINECONE_API_KEY"))
        index = rag.pc.Index("abhyasam-index")
        index.describe_index_stats()

        loader = NotionPageLoader(os.getenv("NOTION_TOKEN"))
        loader.search_all_pages()

        return {
            "status": "success",
            "components": {
                "fastapi": "running",
                "pinecone": "connected",
                "notion": "connected",
                "groq": "initialized"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")
