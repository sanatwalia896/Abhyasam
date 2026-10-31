"""Reuse cleared GCS object names instead of creating new quiz/deck filenames."""
import json

from google.api_core.exceptions import NotFound


def is_empty_slot(data, field):
    return data == {} or (isinstance(data, dict) and (data.get("empty") is True or data.get(field) == []))


def slot_data(blob):
    from question_bank import QuizStorageError
    raw = blob.download_as_text(timeout=30)
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as error:
        raise QuizStorageError(f"Stored object '{blob.name}' contains invalid JSON.") from error


def field_for(prefix):
    return "flashcards" if prefix.startswith("flashcards/") else "questions"


def active_count(bucket, prefix):
    field = field_for(prefix)
    return sum(not is_empty_slot(slot_data(blob), field)
               for blob in bucket.list_blobs(prefix=prefix) if blob.name.endswith(".json"))


def reusable_slot(bucket, prefix, limit=10):
    """Call under the collection lease. Prefer old empty names, including legacy IDs."""
    field = field_for(prefix)
    blobs = sorted((blob for blob in bucket.list_blobs(prefix=prefix) if blob.name.endswith(".json")), key=lambda blob: blob.name)
    for blob in blobs:
        if is_empty_slot(slot_data(blob), field):
            blob.reload(timeout=30)
            return blob, blob.name[len(prefix):-5], blob.generation
    existing = {blob.name for blob in blobs}
    for number in range(1, limit + 1):
        name = f"{prefix}slot-{number:02d}.json"
        if name not in existing:
            return bucket.blob(name), f"slot-{number:02d}", 0
    from question_bank import QuizLimitError
    raise QuizLimitError("All storage slots are occupied. Clear a set/deck before generating another.")


def clear_slot(blob, field, identity_key, identity):
    """Write a small, valid empty JSON object; do not issue a GCS delete."""
    try:
        blob.reload(timeout=30)
        generation = blob.generation
        raw = blob.download_as_text(if_generation_match=generation, timeout=30)
        try:
            if is_empty_slot(json.loads(raw) if raw.strip() else {}, field):
                return
        except json.JSONDecodeError:
            pass  # Explicitly clearing a corrupted slot is allowed.
        blob.upload_from_string(
            json.dumps({identity_key: identity, field: [], "empty": True}),
            content_type="application/json", if_generation_match=generation, timeout=30, retry=None,
        )
    except NotFound as error:
        raise FileNotFoundError("The stored set/deck was not found.") from error
