from fastapi import FastAPI,Query
from fastapi.staticfiles import StaticFiles 
from fastapi.responses import HTMLResponse 
from notion_loader import NotionPageLoader
from chatbot import RevisionAIChat
from vectorstore.rag_creator import RagCreator
import os
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# Mount the static folder to serve HTML, CSS, and JS
app.mount("/static", StaticFiles(directory="static"), name="static")

chatbot=RevisionAIChat(model_name="llama3-8b-8192")


@app.get('/',response_class=HTMLResponse)
async def serve_index():
    with open('static/index.html','r') as f:
        return HTMLResponse(content=f.read())

@app.post("/api/refresh-notion")
async def refresh_notion(force: bool = False, specific_page_id: str | None = None):
    try:
        loader = NotionPageLoader(token=os.getenv("NOTION_TOKEN"), parent_page_id=os.getenv("NOTION_PARENT_PAGE_ID"))
        pages = loader.refresh_and_cache_pages(force_refresh=force)
        
        # Vectorize pages
        rag = RagCreator()
        vector_result = rag.create_vectorstore(pages, specific_page_id=specific_page_id)
        
        return {
            "status": "success",
            "pages_updated": len(vector_result["pages"]),
            "new_pages": len(vector_result["new_pages"]),
            "updated_pages": len(vector_result["updated_pages"]),
            "pages": vector_result["pages"]
        }
    except Exception as e:
        logger.error(f"Error refreshing Notion: {e}")
        return {"status": "error", "message": str(e)}


# Fetch cached Notion pages
@app.get("/api/notion-pages")
async def fetch_notion_pages():
    try:
        loader = NotionPageLoader(os.getenv("NOTION_TOKEN"), os.getenv("NOTION_PARENT_PAGE_ID"))
        pages = loader.get_all_page_contents()
        return pages
    except Exception as e:
        logger.error(f"Error fetching Notion pages: {e}")
        return {"status": "error", "message": str(e)}

# Chat endpoint
@app.post("/api/chat")
async def chat(question: str = Query(...), session_id: str = Query("user1"), model_name: str = Query("openai/gpt-oss-120b")):
    try:
        global chatbot
        # Reinitialize chatbot if model changes
        if chatbot.model_name != model_name:
            chatbot = RevisionAIChat(model_name=model_name)
        response = chatbot.ask_question(question, session_id)
        return response
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/generate-quiz")
async def generate_quiz(page_id: str = Query(...)):
    try:
        # Placeholder: Generate quiz questions (will use Groq later)
        questions = [
            {"question": f"Sample question for page {page_id}", "type": "short_answer", "answer": ""}
        ]
        # Save to questions.json
        with open("static/questions.json", "w") as f:
            json.dump(questions, f, indent=2)
        return {"status": "success", "quiz_url": "/static/quiz.html"}
    except Exception as e:
        logger.error(f"Error generating quiz: {e}")
        return {"status": "error", "message": str(e)}
    
@app.get('/api/test')
async def test_endpoint():
    return {"message": "Hello from FastAPI!"}