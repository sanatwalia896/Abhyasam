"""FastAPI API for GCS-backed quizzes, study tools, and the frontend."""
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import GoogleAuthError
from pydantic import BaseModel, ConfigDict, Field

from chatbot import AbhyasamChat
from mcq_service import MCQ, MCQService, QuizGenerationError, grade
from notion_loader import NotionPageLoader
from populate_vectors import sync_notion_pages
from question_bank import (
    QuizLimitError, QuizStorageError, delete_question_set, get_question_set,
    list_question_sets, rename_question_set,
)
from cloud_artifacts import save_deck, get_deck, list_decks, delete_deck, ensure_deck_capacity
from collection_limit import CollectionBusyError
from groq_pacing import ProviderRateLimitError

logger = logging.getLogger(__name__)
app = FastAPI(
    title="Abhyasam",
    description="MCQ sets are generated, stored, loaded, and scored using Google Cloud Storage.",
    version="3.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@lru_cache(maxsize=1)
def get_chatbot():
    # Browsing existing GCS sets does not initialize embeddings or Pinecone.
    return AbhyasamChat()


class RequestModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AskRequest(RequestModel):
    question: str = Field(min_length=1, max_length=10000)
    session_id: str = Field(default="student1", min_length=1, max_length=100)
    page_title: str | None = None


class QuizRequest(RequestModel):
    topic_query: str = Field(default="key concepts", max_length=300)
    num_batches: int = Field(default=1, ge=1, le=20)
    questions_per_batch: int = Field(default=10, ge=1, le=50)
    page_title: str | None = None


class MCQRequest(RequestModel):
    topic_query: str = Field(default="", max_length=300, description="Optional subject within the selected page. Leave blank to cover the page.")
    num_questions: int = Field(default=10, ge=1, le=1000)
    page_title: str | None = None
    title: str | None = Field(default=None, max_length=150)


class RenameQuizRequest(RequestModel):
    title: str = Field(min_length=1, max_length=150)


class MCQGenerationResponse(BaseModel):
    status: str = "success"
    set_id: str
    requested_count: int
    unique_chunks: int
    capacity: int
    target_count: int
    generated_count: int
    capacity_basis: str
    topic_query: str
    chunk_decisions: dict[str, int] = Field(default_factory=dict)


class QuizSummary(BaseModel):
    id: str
    title: str
    page_title: str | None = None
    question_count: int
    created_at: str | None = None


class QuizListResponse(BaseModel):
    status: str = "success"
    question_sets: list[QuizSummary]


class CloudQuiz(BaseModel):
    id: str
    revision: str | None = None
    title: str = "Untitled quiz"
    page_title: str | None = None
    created_at: str | None = None
    questions: list[MCQ]
    generation: dict = Field(default_factory=dict)


class QuizResponse(BaseModel):
    status: str = "success"
    question_set: CloudQuiz


class MCQAnswers(RequestModel):
    answers: dict[str, Literal["A", "B", "C", "D"]] = Field(default_factory=dict)
    revision: str | None = None


class StartQuizRequest(RequestModel):
    num_questions: int = Field(default=5, ge=1, le=50)
    session_id: str = Field(default="student1", min_length=1, max_length=100)
    page_title: str | None = None


class SubmitAnswerRequest(RequestModel):
    answer: str = Field(min_length=1, max_length=10000)
    session_id: str = Field(default="student1", min_length=1, max_length=100)


class FlashcardRequest(RequestModel):
    topic_query: str = Field(default="key concepts", min_length=1, max_length=300)
    num_batches: int = Field(default=1, ge=1, le=4)
    flashcards_per_batch: int = Field(default=5, ge=1, le=20)
    page_title: str | None = None


# Provider failures and invalid JSON are distinguished from request validation.
@app.exception_handler(FileNotFoundError)
async def not_found(request, error):
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(QuizLimitError)
@app.exception_handler(CollectionBusyError)
async def library_full(request, error):
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(QuizStorageError)
async def invalid_stored_quiz(request, error):
    logger.error("Stored quiz could not be read: %s", error)
    return JSONResponse(status_code=502, content={"detail": str(error)})


@app.exception_handler(QuizGenerationError)
async def invalid_generated_quiz(request, error):
    logger.error("MCQ generation failed: %s", error)
    return JSONResponse(status_code=502, content={"detail": str(error)})


async def storage_unavailable(request, error):
    logger.exception("Cloud storage request failed")
    return JSONResponse(status_code=503, content={
        "detail": "Google Cloud Storage is unavailable or credentials lack access. Check the backend logs."
    })


app.add_exception_handler(GoogleAPICallError, storage_unavailable)
app.add_exception_handler(GoogleAuthError, storage_unavailable)


@app.exception_handler(ProviderRateLimitError)
async def groq_limited(request, error):
    return JSONResponse(status_code=429, content={"detail": str(error)}, headers={"Retry-After": str(error.retry_after)})


@app.exception_handler(Exception)
async def provider_failure(request, error):
    logger.exception("Request failed: %s", request.url.path)
    return JSONResponse(status_code=502, content={
        "detail": "The study service could not complete this request. Check the backend logs for the provider error."
    })


@app.get("/")
def root() -> dict:
    return {"status": "ok", "message": "Welcome to Abhyasam API", "ui": "/index.html"}


@app.get("/api/runtime-info")
def runtime_info() -> dict:
    return {
        "status": "ok", "api_version": "quiz-bank-v3",
        "pinecone_index": os.getenv("PINECONE_INDEX_NAME", "abhyasam-fastembed-index"),
        "pinecone_namespace": os.getenv("PINECONE_NAMESPACE", "notion-knowledge"),
        "groq_model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        "quiz_storage": "gcs", "question_set_endpoints": True,
    }


# Synchronous SDK work runs in FastAPI's worker threads.
@app.post("/api/refresh-notion")
def refresh_notion(force: bool = False) -> dict:
    return {"status": "success", **sync_notion_pages(force=force)}


@app.get("/api/notion-pages")
def fetch_notion_pages() -> dict:
    from state_updates import load_state
    state = load_state()
    pages = [{"page_id": page_id, "title": page.get("title", "Untitled")}
             for page_id, page in state["pages"].items()]
    return {"status": "success", "pages": pages}


@app.post("/api/chat")
def chat(req: AskRequest) -> dict:
    response = get_chatbot().ask_question(req.question, req.session_id, req.page_title)
    return {"status": "success", "answer": response["answer"], "page_title": req.page_title or "All pages"}


@app.post("/api/start-quiz", deprecated=True, tags=["Legacy compatibility"])
@app.post("/api/short-answer/sessions", tags=["Short answer"])
def start_quiz(req: StartQuizRequest) -> dict:
    return get_chatbot().start_interactive_quiz(req.session_id, req.num_questions, req.page_title)


@app.post("/api/submit-quiz-answer", deprecated=True, tags=["Legacy compatibility"])
@app.post("/api/short-answer/answers", tags=["Short answer"])
def submit_quiz_answer(req: SubmitAnswerRequest) -> dict:
    return get_chatbot().submit_quiz_answer(req.session_id, req.answer)


def create_mcq(req: MCQRequest) -> dict:
    try:
        result = MCQService(get_chatbot()).generate(
            req.topic_query, req.num_questions, req.page_title, req.title,
        )
        return {"status": "success", **{key: value for key, value in result.items() if key != "questions"}}
    except (QuizLimitError, QuizGenerationError, QuizStorageError, ProviderRateLimitError):
        raise
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (GoogleAPICallError, GoogleAuthError):
        raise
    except Exception as error:
        logger.exception("MCQ generation provider failed")
        raise QuizGenerationError("Quiz generation failed. Check the backend logs for the provider error.") from error


@app.post("/api/mcq/sets/generate", tags=["MCQ"], response_model=MCQGenerationResponse, status_code=201)
def generate_mcq_set(req: MCQRequest) -> dict:
    return create_mcq(req)


@app.post("/api/generate-quiz", deprecated=True, tags=["Legacy compatibility"])
def generate_quiz(req: QuizRequest) -> dict:
    result = create_mcq(MCQRequest(
        topic_query=req.topic_query,
        num_questions=req.num_batches * req.questions_per_batch,
        page_title=req.page_title,
    ))
    return {**result, "questions_count": result["generated_count"]}


@app.get("/api/mcq/sets", tags=["MCQ"], response_model=QuizListResponse)
@app.get("/api/question-sets", deprecated=True, tags=["Legacy compatibility"])
def get_question_sets() -> dict:
    return {"status": "success", "question_sets": list_question_sets()}


@app.get("/api/mcq/sets/{set_id}", tags=["MCQ"], response_model=QuizResponse)
@app.get("/api/question-sets/{set_id}", deprecated=True, tags=["Legacy compatibility"])
def get_question_set_by_id(set_id: str) -> dict:
    return {"status": "success", "question_set": get_question_set(set_id)}


@app.get("/api/questions", deprecated=True, tags=["Legacy compatibility"])
def get_questions(set_id: str) -> dict:
    """Compatibility route: explicit set ID, always downloaded from GCS."""
    return {"status": "success", "questions": get_question_set(set_id)["questions"]}


@app.post("/api/mcq/sets/{set_id}/submit", tags=["MCQ"])
def submit_mcq(set_id: str, req: MCQAnswers) -> dict:
    saved = get_question_set(set_id)  # Download correct answers from GCS for every submission.
    if saved.get("revision") and req.revision != saved["revision"]:
        raise HTTPException(status_code=409, detail="This storage slot now contains a different quiz. Reload the quiz before submitting.")
    valid_ids = {q.get("id") or f"q{index+1}" for index, q in enumerate(saved["questions"])}
    if set(req.answers) - valid_ids:
        raise HTTPException(status_code=422, detail="Answers contain question IDs outside this quiz.")
    return {"status": "success", **grade(saved, req.answers)}


@app.patch("/api/mcq/sets/{set_id}", tags=["MCQ"], response_model=QuizResponse)
def rename_mcq(set_id: str, req: RenameQuizRequest) -> dict:
    return {"status": "success", "question_set": rename_question_set(set_id, req.title)}


@app.delete("/api/mcq/sets/{set_id}", tags=["MCQ"])
@app.delete("/api/question-sets/{set_id}", deprecated=True, tags=["Legacy compatibility"])
def delete_question_set_by_id(set_id: str) -> dict:
    delete_question_set(set_id)
    return {"status": "success", "cleared": set_id}


# Each generated flashcard deck is persisted independently in GCS.
@app.post("/api/generate-flashcards")
def generate_flashcards(req: FlashcardRequest) -> dict:
    ensure_deck_capacity()
    cards = get_chatbot().generate_flashcards(
        req.topic_query, req.num_batches, req.flashcards_per_batch, req.page_title,
    )
    if not cards:
        raise HTTPException(status_code=502, detail="No flashcards generated from the selected material.")
    return {"status": "success", "flashcards_count": len(cards), **save_deck(cards, req.page_title)}


@app.get("/api/flashcards")
def get_flashcards(deck_id: str) -> dict:
    return {"status": "success", **get_deck(deck_id)}


@app.get("/api/flashcard-decks", tags=["Flashcards"])
def get_flashcard_decks() -> dict:
    return {"status": "success", "decks": list_decks(), "limit": 10}


@app.delete("/api/flashcard-decks/{deck_id}", tags=["Flashcards"])
def remove_flashcard_deck(deck_id: str) -> dict:
    delete_deck(deck_id)
    return {"status": "success", "cleared": deck_id}


@app.get("/api/health")
def health_check() -> dict:
    return {"status": "ok", "api_version": app.version}


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.is_dir() and os.getenv("SERVE_FRONTEND", "true").lower() == "true":
    app.mount("/", FrontendFiles(directory=str(frontend_dir), html=True), name="frontend")
