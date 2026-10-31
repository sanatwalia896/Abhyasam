"""Synchronize Notion pages into Pinecone using GCS sync state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from fastembed import TextEmbedding
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone, ServerlessSpec

from notion_loader import NotionPageLoader
from state_updates import load_state, save_state
from embedding_runtime import embedding_model

load_dotenv()

INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "abhyasam-fastembed-index")
NAMESPACE = os.getenv("PINECONE_NAMESPACE", "notion-knowledge")
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSION = 384


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def vector_id(page_id: str, chunk_index: int) -> str:
    raw = f"notion:{page_id}:{chunk_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AbhyasamRAG:
    """Direct FastEmbed + Pinecone client; no LangChain vector store."""

    def __init__(
        self,
        api_key: str,
        index_name: str = INDEX_NAME,
        namespace: str = NAMESPACE,
        cloud: str = "aws",
        region: str = "us-east-1",
    ):
        if not api_key:
            raise ValueError("PINECONE_API_KEY is missing")

        self.index_name = index_name
        self.namespace = namespace
        self.dimension = EMBEDDING_DIMENSION

        print("Loading embedding model (downloads on first run)...")
        self.embeddings = embedding_model()

        self.pc = Pinecone(api_key=api_key)
        if not self.pc.has_index(self.index_name):
            print(f"Creating Pinecone index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud=cloud, region=region),
            )

        self.index = self.pc.Index(self.index_name)
        print(f"Pinecone ready: {self.index_name}/{namespace}")

    def upsert_documents(
        self,
        documents: list[Document],
        namespace: str | None = None,
        batch_size: int = 100,
    ) -> int:
        namespace = namespace or self.namespace
        total = 0

        for batch_start in range(0, len(documents), batch_size):
            batch = documents[batch_start:batch_start + batch_size]
            texts: list[str] = []
            metadata_list: list[dict[str, Any]] = []

            for document in batch:
                text = document.page_content.strip()
                if text:
                    texts.append(text)
                    metadata_list.append(dict(document.metadata or {}))

            if not texts:
                continue

            embeddings = list(self.embeddings.embed(texts))
            if len(embeddings) != len(texts):
                raise RuntimeError("Embedding count does not match document count")

            vectors = []
            for offset, (text, embedding, metadata) in enumerate(
                zip(texts, embeddings, metadata_list)
            ):
                page_id = str(metadata.get("page_id", "unknown-page"))
                chunk_index = int(metadata.get("chunk_index", batch_start + offset))
                values = embedding.tolist()

                if len(values) != self.dimension:
                    raise ValueError(
                        f"Expected {self.dimension} dimensions, got {len(values)}"
                    )

                clean_metadata = {
                    key: value
                    for key, value in metadata.items()
                    if isinstance(value, (str, int, float, bool))
                }
                clean_metadata.update({
                    "page_id": page_id,
                    "chunk_index": chunk_index,
                    "text": text[:1000],
                })

                vectors.append({
                    "id": vector_id(page_id, chunk_index),
                    "values": values,
                    "metadata": clean_metadata,
                })

            self.index.upsert(vectors=vectors, namespace=namespace)
            total += len(vectors)
            print(f"Upserted {len(vectors)} vectors")

        return total

    def delete_page_chunks(
        self,
        page_id: str,
        start_index: int,
        end_index: int,
        namespace: str | None = None,
    ) -> None:
        namespace = namespace or self.namespace
        if end_index <= start_index:
            return
        ids = [vector_id(page_id, index) for index in range(start_index, end_index)]
        self.index.delete(ids=ids, namespace=namespace)
        print(f"Deleted {len(ids)} stale vectors for page {page_id}")


def split_page(page_id: str, title: str, content: str) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
    )
    source = Document(
        page_content=content,
        metadata={
            "source": "Notion",
            "page_id": page_id,
            "page_title": title,
        },
    )
    chunks = splitter.split_documents([source])
    for chunk_index, chunk in enumerate(chunks):
        chunk.metadata.update({
            "source": "Notion",
            "page_id": page_id,
            "page_title": title,
            "chunk_index": chunk_index,
        })
    return chunks


def sync_notion_pages(force: bool = False, dry_run: bool = False) -> dict[str, int]:
    notion_token = os.getenv("NOTION_TOKEN")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    if not notion_token:
        raise ValueError("NOTION_TOKEN is missing")
    if not pinecone_key:
        raise ValueError("PINECONE_API_KEY is missing")

    loader = NotionPageLoader(notion_token)
    state = load_state()
    page_ids = loader.search_all_pages()
    current_page_ids = set(page_ids)
    rag = None if dry_run else AbhyasamRAG(pinecone_key)
    changed = skipped = failed = 0

    for position, page_id in enumerate(page_ids, start=1):
        try:
            title = loader.get_page_title(page_id)
            blocks = loader.get_page_blocks(page_id)
            content = "\n".join(
                block["text"].strip()
                for block in blocks
                if block.get("text", "").strip()
            ).strip()

            if not content:
                print(f"[{position}/{len(page_ids)}] Empty page: {title}")
                continue

            digest = content_hash(content)
            previous = state["pages"].get(page_id, {})
            if (
                not force
                and previous.get("content_hash") == digest
                and previous.get("status") == "synced"
            ):
                skipped += 1
                print(f"[{position}/{len(page_ids)}] Unchanged: {title}")
                continue

            documents = split_page(page_id, title, content)
            new_count = len(documents)
            old_count = int(previous.get("chunk_count", 0))

            if dry_run:
                changed += 1
                print(f"[{position}/{len(page_ids)}] Would sync: {title} ({new_count} chunks)")
                continue

            assert rag is not None
            rag.upsert_documents(documents)
            rag.delete_page_chunks(page_id, new_count, old_count)
            state["pages"][page_id] = {
                "page_id": page_id,
                "title": title,
                "content_hash": digest,
                "chunk_count": new_count,
                "status": "synced",
                "synced_at": utc_now(),
            }
            changed += 1
            print(f"[{position}/{len(page_ids)}] Synced: {title}")

        except Exception as error:
            failed += 1
            print(f"[{position}/{len(page_ids)}] Failed {page_id}: {error}")

    if not dry_run and rag is not None:
        deleted_page_ids = set(state["pages"]) - current_page_ids
        for page_id in deleted_page_ids:
            old_count = int(state["pages"][page_id].get("chunk_count", 0))
            rag.delete_page_chunks(page_id, 0, old_count)
            del state["pages"][page_id]

        if changed or deleted_page_ids:
            save_state(state)

        # Keep the lightweight file used by the frontend page selector in sync.
        os.makedirs("data", exist_ok=True)
        with open("data/page_id_with_titles.json", "w", encoding="utf-8") as file:
            json.dump(
                [
                    {
                        "page_id": page_id,
                        "title": page.get("title", "Untitled"),
                    }
                    for page_id, page in state["pages"].items()
                ],
                file,
                indent=2,
                ensure_ascii=False,
            )

    summary = {
        "discovered": len(page_ids),
        "changed": changed,
        "skipped": skipped,
        "failed": failed,
    }
    print(f"Sync summary: {summary}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Notion pages to Pinecone")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sync_notion_pages(force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
