"""Read and update sync_state.json in Google Cloud Storage.

Usage:
    python state_updates.py --show
    python state_updates.py --page-id PAGE_ID --title "Page title" --chunks 12

The module can also be imported by the Notion ingestion pipeline:
    from state_updates import update_page_state
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import find_dotenv, load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import storage


load_dotenv(find_dotenv())

DEFAULT_BLOB_NAME = "sync_state.json"
DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "updated_at": None,
    "pages": {},
}


def _client_and_blob(
    blob_name: str = DEFAULT_BLOB_NAME,
):
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    bucket_name = os.getenv("GCS_BUCKET_NAME", "abhyasam-1234")

    if not project_id:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is missing")

    if not bucket_name:
        raise RuntimeError("GCS_BUCKET_NAME is missing")

    client = storage.Client(project=project_id)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return client, bucket, blob


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(blob_name: str = DEFAULT_BLOB_NAME) -> dict[str, Any]:
    """Download sync_state.json, or return an empty state if it does not exist."""
    _, bucket, blob = _client_and_blob(blob_name)

    try:
        raw_state = blob.download_as_text(encoding="utf-8")
    except NotFound:
        return {
            "version": DEFAULT_STATE["version"],
            "updated_at": None,
            "pages": {},
        }

    # A newly-created GCS object can exist with zero bytes. Treat it as an
    # empty state, then the next successful sync will replace it with JSON.
    if not raw_state.strip():
        print(
            f"Warning: gs://{bucket.name}/{blob_name} is empty; "
            "starting with an empty sync state."
        )
        return {
            "version": DEFAULT_STATE["version"],
            "updated_at": None,
            "pages": {},
        }

    try:
        state = json.loads(raw_state.lstrip("\ufeff"))
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"{bucket.name}/{blob_name} is not valid JSON"
        ) from error

    if not isinstance(state, dict):
        raise RuntimeError("Sync state must be a JSON object")

    state.setdefault("version", 1)
    state.setdefault("updated_at", None)
    state.setdefault("pages", {})

    if not isinstance(state["pages"], dict):
        raise RuntimeError("The 'pages' field must be a JSON object")

    return state


def save_state(
    state: dict[str, Any],
    blob_name: str = DEFAULT_BLOB_NAME,
) -> None:
    """Upload the complete sync state as formatted JSON."""
    _, bucket, blob = _client_and_blob(blob_name)

    state["updated_at"] = _now()
    payload = json.dumps(state, indent=2, ensure_ascii=False) + "\n"

    blob.upload_from_string(
        payload,
        content_type="application/json",
    )

    print(f"Saved gs://{bucket.name}/{blob_name}")


def update_page_state(
    page_id: str,
    *,
    title: str = "",
    content_hash: str = "",
    chunk_count: int = 0,
    status: str = "synced",
    blob_name: str = DEFAULT_BLOB_NAME,
) -> dict[str, Any]:
    """Update one Notion page and persist the new state."""
    if not page_id.strip():
        raise ValueError("page_id cannot be empty")

    state = load_state(blob_name)
    state["pages"][page_id] = {
        "page_id": page_id,
        "title": title,
        "content_hash": content_hash,
        "chunk_count": int(chunk_count),
        "status": status,
        "synced_at": _now(),
    }
    save_state(state, blob_name)
    return state


def remove_page_state(
    page_id: str,
    blob_name: str = DEFAULT_BLOB_NAME,
) -> dict[str, Any]:
    """Remove one page from the sync state and persist the result."""
    state = load_state(blob_name)
    state["pages"].pop(page_id, None)
    save_state(state, blob_name)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Notion sync state")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--page-id")
    parser.add_argument("--title", default="")
    parser.add_argument("--content-hash", default="")
    parser.add_argument("--chunks", type=int, default=0)
    parser.add_argument("--status", default="synced")
    parser.add_argument("--remove-page")
    args = parser.parse_args()

    if args.show:
        print(json.dumps(load_state(), indent=2, ensure_ascii=False))
        return

    if args.remove_page:
        remove_page_state(args.remove_page)
        return

    if args.page_id:
        update_page_state(
            args.page_id,
            title=args.title,
            content_hash=args.content_hash,
            chunk_count=args.chunks,
            status=args.status,
        )
        return

    parser.error("Use --show, --remove-page, or --page-id")


if __name__ == "__main__":
    main()
