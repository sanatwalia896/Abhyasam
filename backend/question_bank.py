"""Persistent MCQ question sets stored as JSON objects in Google Cloud Storage."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from google.api_core.exceptions import NotFound
from google.cloud import storage
from collection_limit import limited_collection
from storage_slots import is_empty_slot, reusable_slot, clear_slot, slot_data


PREFIX = "quiz/question_sets/"
MAX_SETS = 10


class QuizStorageError(RuntimeError):
    """A GCS quiz object contains invalid JSON or invalid quiz data."""


class QuizLimitError(RuntimeError):
    """The quiz library has reached its configured limit."""


def _read_quiz(blob):
    try:
        data = slot_data(blob)
        if is_empty_slot(data, "questions"):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise ValueError("Missing quiz ID")
        questions = data.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError("Quiz has no questions")
        for index, question in enumerate(questions):
            if not isinstance(question, dict) or not isinstance(question.get("question"), str):
                raise ValueError("Invalid question")
            options = question.get("options")
            if not isinstance(options, dict) or set(options) != set("ABCD"):
                raise ValueError("Question requires A/B/C/D options")
            if any(not isinstance(value, str) or not value.strip() for value in options.values()):
                raise ValueError("Invalid options")
            if question.get("answer") not in ("A", "B", "C", "D"):
                raise ValueError("Invalid correct answer")
            question["id"] = question.get("id") or f"q{index+1}"
        if len({q["id"] for q in questions}) != len(questions):
            raise ValueError("Duplicate question IDs")
        # Reuse the API schema so malformed stored questions produce a storage
        # error here rather than a response-validation error later in FastAPI.
        from mcq_service import MCQ
        data["questions"] = [MCQ.model_validate(question).model_dump() for question in questions]
        return data
    except (ValueError, TypeError) as error:
        raise QuizStorageError(
            f"Stored quiz '{blob.name}' is malformed. It could not be loaded from GCS."
        ) from error


def _blob(name: str):
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    bucket_name = os.getenv("GCS_BUCKET_NAME", "abhyasam-1234")
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is missing")
    client = storage.Client(project=project)
    bucket = client.bucket(bucket_name)
    return bucket, bucket.blob(name)


def list_question_sets() -> list[dict[str, Any]]:
    bucket, _ = _blob(PREFIX)
    result = []
    for blob in bucket.list_blobs(prefix=PREFIX):
        if not blob.name.endswith(".json"):
            continue
        try:
            data = _read_quiz(blob)
            if data is None:
                continue
            result.append({
                "id": data["id"],
                "title": data.get("title", "Untitled quiz"),
                "page_title": data.get("page_title"),
                "question_count": len(data.get("questions", [])),
                "created_at": data.get("created_at"),
            })
        except QuizStorageError:
            # Surface corrupted objects rather than silently hiding them.
            raise
    return sorted(result, key=lambda item: item.get("created_at") or "", reverse=True)


def get_question_set(set_id: str) -> dict[str, Any]:
    _, blob = _blob(f"{PREFIX}{set_id}.json")
    try:
        data = _read_quiz(blob)
        if data is None:
            raise FileNotFoundError("This quiz has been cleared. Generate or select another quiz.")
        return data
    except NotFound as error:
        raise FileNotFoundError(f"Question set {set_id} was not found") from error


def save_question_set(
    questions: list[dict[str, Any]],
    *,
    title: str = "Abhyasam Quiz",
    page_title: str | None = None,
    generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = list_question_sets()
    if len(existing) >= MAX_SETS:
        raise QuizLimitError(
            f"Question-set limit reached ({MAX_SETS}). Clear a set first."
        )

    data = {
        "revision": uuid4().hex,
        "title": title,
        "page_title": page_title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "questions": questions,
        "generation": generation or {},
    }
    bucket, _ = _blob(PREFIX)
    with limited_collection(PREFIX, MAX_SETS):
        blob, set_id, generation_match = reusable_slot(bucket, PREFIX, MAX_SETS)
        data["id"] = set_id
        blob.upload_from_string(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            content_type="application/json",
            if_generation_match=generation_match,
            timeout=30,
            retry=None,
        )
    return data


def rename_question_set(set_id: str, title: str) -> dict[str, Any]:
    with limited_collection(PREFIX, MAX_SETS, check_capacity=False):
        data = get_question_set(set_id)
        data["title"] = title.strip()
        _, blob = _blob(f"{PREFIX}{set_id}.json")
        blob.reload(timeout=30)
        blob.upload_from_string(json.dumps(data, ensure_ascii=False), content_type="application/json",
                                if_generation_match=blob.generation, timeout=30, retry=None)
    return data


def delete_question_set(set_id: str) -> None:
    _, blob = _blob(f"{PREFIX}{set_id}.json")
    with limited_collection(PREFIX, MAX_SETS, check_capacity=False):
        clear_slot(blob, "questions", "id", set_id)
