"""Persistent flashcard decks and session state; no container filesystem state."""
import hashlib
import json
from uuid import uuid4
from datetime import datetime, timezone

from google.api_core.exceptions import NotFound
from question_bank import _blob, QuizStorageError, QuizLimitError
from collection_limit import limited_collection
from storage_slots import is_empty_slot, reusable_slot, clear_slot

DECK_PREFIX = "flashcards/decks/"
MAX_DECKS = 10


def list_decks():
    bucket, _ = _blob(DECK_PREFIX)
    decks = []
    for blob in bucket.list_blobs(prefix=DECK_PREFIX):
        if not blob.name.endswith(".json"):
            continue
        data = read_json(blob.name)
        if is_empty_slot(data, "flashcards"):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("flashcards"), list):
            raise QuizStorageError(f"Invalid flashcard deck: {blob.name}")
        decks.append({"deck_id": data["deck_id"], "page_title": data.get("page_title"),
                      "card_count": len(data["flashcards"]), "created_at": data.get("created_at", "")})
    return sorted(decks, key=lambda item: item["created_at"], reverse=True)


def ensure_deck_capacity():
    if len(list_decks()) >= MAX_DECKS:
        raise QuizLimitError("Your flashcard library contains 10 decks. Clear one before generating another.")


def delete_deck(deck_id):
    _, blob = _blob(f"{DECK_PREFIX}{deck_id}.json")
    with limited_collection(DECK_PREFIX, MAX_DECKS, check_capacity=False):
        clear_slot(blob, "flashcards", "deck_id", deck_id)


def write_json(name, data):
    _, blob = _blob(name)
    blob.upload_from_string(json.dumps(data, ensure_ascii=False), content_type="application/json", timeout=30, retry=None)


def read_json(name, missing=None):
    _, blob = _blob(name)
    try:
        return json.loads(blob.download_as_text(timeout=30))
    except NotFound:
        return missing
    except json.JSONDecodeError as error:
        raise QuizStorageError(f"Stored object '{name}' contains invalid JSON") from error


def save_deck(cards, page_title):
    data = {"revision": uuid4().hex, "page_title": page_title, "flashcards": cards,
            "created_at": datetime.now(timezone.utc).isoformat()}
    bucket, _ = _blob(DECK_PREFIX)
    with limited_collection(DECK_PREFIX, MAX_DECKS):
        blob, deck_id, generation_match = reusable_slot(bucket, DECK_PREFIX, MAX_DECKS)
        data["deck_id"] = deck_id
        blob.upload_from_string(json.dumps(data, ensure_ascii=False), content_type="application/json",
                                if_generation_match=generation_match, timeout=30, retry=None)
    return data


def get_deck(deck_id):
    data = read_json(f"flashcards/decks/{deck_id}.json")
    if data is None or is_empty_slot(data, "flashcards"):
        raise FileNotFoundError("Flashcard deck was not found. Generate a deck for your selected page.")
    if not isinstance(data, dict) or not isinstance(data.get("flashcards"), list) or not data["flashcards"]:
        raise QuizStorageError("Stored flashcard deck is empty or malformed.")
    if any(not isinstance(card, dict) or any(not isinstance(card.get(side), str) or not card[side].strip() for side in ("front", "back")) for card in data["flashcards"]):
        raise QuizStorageError("Stored flashcard deck contains an invalid card.")
    return data


def session_name(kind, session_id):
    key = hashlib.sha256(session_id.encode()).hexdigest()
    return f"sessions/{kind}/{key}.json"


def load_session(kind, session_id):
    return read_json(session_name(kind, session_id))


def save_session(kind, session_id, data):
    write_json(session_name(kind, session_id), data)
