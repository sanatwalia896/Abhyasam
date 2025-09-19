
import os
import json
from typing import List
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceInferenceAPIEmbeddings

from langchain_pinecone import PineconeVectorStore
from langchain.text_splitter import RecursiveCharacterTextSplitter
from notion_loader import NotionPageLoader
from dotenv import load_dotenv
from populate_vectors import AbhyasamRAG

# Load environment variables
load_dotenv()

def get_new_page_ids(notion_loader, json_path: str = "page_id_with_title.json") -> List[str]:
    """Compare current Notion pages with stored JSON to find new page IDs."""
    # Fetch all page IDs
    page_ids = notion_loader.search_all_pages()
    # Create title: ID dictionary
    page_title = {notion_loader.get_page_title(page_id): page_id for page_id in page_ids}

    # Load existing pages from JSON
    try:
        with open(json_path, 'r') as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = {}

    # Find new or changed pages
    new_ids = []
    for title, page_id in page_title.items():
        if title not in existing or existing[title] != page_id:
            new_ids.append(page_id)
            existing[title] = page_id  # Update JSON

    # Save updated JSON
    with open(json_path, 'w') as f:
        json.dump(existing, f, indent=2)

    return new_ids

def populate_new_pages():
    """Populate only new Notion pages into Pinecone using HuggingFace embeddings."""
    # Load environment variables
    notion_token = os.getenv("NOTION_TOKEN")
    hf_token = os.getenv("HUGGINGFACE_TOKEN")
    pinecone_api_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME")

    if not all([notion_token, hf_token, pinecone_api_key, index_name]):
        raise ValueError("Missing required environment variables")

    # Initialize Notion loader
    notion_loader = NotionPageLoader(notion_token)

    # Get new page IDs
    new_page_ids = get_new_page_ids(notion_loader)
    if not new_page_ids:
        print("No new pages found.")
        return

    # Initialize embeddings and vector store
    embeddings = HuggingFaceInferenceAPIEmbeddings(
    api_key=hf_token,  # make sure you set this in .env
    model_name="sentence-transformers/all-MiniLM-L6-v2",
)
    # vectorstore = PineconeVectorStore.from_existing_index(
    #     index_name=index_name,
    #     embedding=embeddings,
    #     namespace="notion-knowledge",
    #     pinecone_api_key=pinecone_api_key
    # )
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

    # Process new pages
    all_docs = []
    for idx, page_id in enumerate(new_page_ids):
        try:
            page_title = notion_loader.get_page_title(page_id)
            blocks = notion_loader.get_page_blocks(page_id)

            # Merge block text
            content = "\n".join([b["text"] for b in blocks if b.get("text")])

            if not content:
                print(f"No content found for page ID: {page_id}")
                continue

            # Create document
            doc = Document(
                page_content=content,
                metadata={
                    "source": "Notion",
                    "page_title": page_title,
                    "page_id": page_id,
                    "chunk_id": idx,
                },
            )

            # Split into chunks
            chunked_docs = splitter.split_documents([doc])
            all_docs.extend(chunked_docs)
            print(f"Processed page: {page_title} → {len(chunked_docs)} chunks")
        except Exception as e:
            print(f"Error processing page ID {page_id}: {str(e)}")

    # Upsert to Pinecone
    if all_docs:
        print(f"Upserting {len(all_docs)} chunks to Pinecone...")
        PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
        rag = AbhyasamRAG(api_key=PINECONE_API_KEY)
        rag.upsert_documents(all_docs, namespace="notion-knowledge")
        print("🎉 Done")
    else:
        print("No documents to upsert.")

if __name__ == "__main__":
    try:
        populate_new_pages()
    except Exception as e:
        print(f"Error in populate_new_pages: {str(e)}")
