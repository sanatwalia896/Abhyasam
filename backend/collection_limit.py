"""Serialize collection creation across Cloud Run instances using a GCS lease."""
import hashlib
import json
import time
from contextlib import contextmanager

from google.api_core.exceptions import NotFound, PreconditionFailed
from storage_slots import active_count


class CollectionBusyError(RuntimeError):
    pass


@contextmanager
def limited_collection(prefix, limit=10, *, check_capacity=True):
    from question_bank import _blob, QuizLimitError
    name = "system/locks/" + hashlib.sha256(prefix.encode()).hexdigest() + ".json"
    bucket, lock = _blob(name)
    expires = time.time() + 600
    payload = json.dumps({"expires_at": expires})
    try:
        lock.upload_from_string(payload, if_generation_match=0, content_type="application/json", timeout=30)
    except PreconditionFailed:
        # Read one exact version; only remove an abandoned lease by its generation.
        try:
            lock.reload(timeout=30)
            generation = lock.generation
            previous = json.loads(lock.download_as_text(if_generation_match=generation, timeout=30))
            if previous.get("expires_at", float("inf")) >= time.time():
                raise CollectionBusyError("Another save is in progress. Please retry in a moment.")
            lock.upload_from_string(payload, if_generation_match=generation, content_type="application/json", timeout=30, retry=None)
        except (NotFound, PreconditionFailed) as error:
            raise CollectionBusyError("Another save is in progress. Please retry.") from error
    generation = lock.generation
    try:
        count = active_count(bucket, prefix) if check_capacity else 0
        if check_capacity and count >= limit:
            raise QuizLimitError(f"This library already contains {limit} sets/decks. Clear one before generating another.")
        if time.time() >= expires - 60:
            raise CollectionBusyError("Saving took too long. Please retry.")
        yield
    finally:
        try:
            lock.upload_from_string(json.dumps({"expires_at": 0}), if_generation_match=generation,
                                    content_type="application/json", timeout=30, retry=None)
        except (NotFound, PreconditionFailed):
            pass
