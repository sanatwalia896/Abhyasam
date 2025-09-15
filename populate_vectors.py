import os
import time
from pathlib import Path
from dotenv import load_dotenv

# Notion loader
from notion_loader import NotionPageLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Pinecone + LangChain
from pinecone import Pinecone, ServerlessSpec
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore


# ---------------- Helpers ----------------
def clean_url_for_title(url: str) -> str:
    return url.split("/")[-1].replace(".md", "")


def generate_ids(doc_chunk: Document) -> str:
    title = doc_chunk.metadata.get("page_title", "unknown")
    chunk_num = doc_chunk.metadata.get("chunk_id", 0)
    feature = doc_chunk.metadata.get("feature", "na")
    return f"notion_{title}#feature_{feature}#chunk{chunk_num}"


# ---------------- RAG Wrapper ----------------
class AbhyasamRAG:
    def __init__(
        self,
        api_key: str,
        index_name: str = "abhyasam-index",
        cloud: str = "aws",
        region: str = "us-east-1",
        namespace: str = "rag",
    ):
        """Initialize Pinecone with HuggingFace embeddings."""
        self.pc = Pinecone(api_key=api_key)
        self.index_name = index_name
        self.cloud = cloud
        self.region = region
        self.namespace = namespace

        self._init_index()

        # HuggingFace embeddings (MiniLM-L6-v2, 384-dim)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            cache_folder="./models",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

        # Initialize LangChain VectorStore
        self.vector_store = PineconeVectorStore.from_existing_index(
            index_name=self.index_name,
            embedding=self.embeddings,
            namespace=self.namespace
        )

    def _init_index(self):
        """Create or connect to Pinecone index."""
        if not self.pc.has_index(self.index_name):
            print(f"Creating Pinecone index {self.index_name}...")
            self.pc.create_index(
                name=self.index_name,
                dimension=384,  # HuggingFace MiniLM-L6-v2
                metric="cosine",
                spec=ServerlessSpec(cloud=self.cloud, region=self.region),
            )
            time.sleep(2)
        else:
            print(f"Using existing index: {self.index_name}")

    def upsert_documents(self, documents: list[Document], namespace: str | None = None):
        """Upsert Notion page chunks into Pinecone via LangChain VectorStore."""
        ids = [generate_ids(doc) for doc in documents]
        self.vector_store.add_documents(documents=documents, ids=ids)
        print(f"✅ Upserted {len(documents)} docs into Pinecone (ns={self.namespace})")


# ---------------- Main Pipeline ----------------
if __name__ == "__main__":
    load_dotenv()

    # Init loaders
    notion_loader = NotionPageLoader(os.getenv("NOTION_TOKEN"))
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

    # Fetch Notion pages
    page_ids = notion_loader.search_all_pages()
    all_docs = []

    for idx, page_id in enumerate(page_ids):
        page_title = notion_loader.get_page_title(page_id)
        blocks = notion_loader.get_page_blocks(page_id)

        # Merge all block text
        content = "\n".join([b["text"] for b in blocks if b.get("text")])

        # Make base document
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

    # Init Pinecone
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    rag = AbhyasamRAG(api_key=PINECONE_API_KEY)

    # Push to Pinecone
    print(f"Upserting {len(all_docs)} chunks to Pinecone...")
    rag.upsert_documents(all_docs, namespace="notion-knowledge")
    print("🎉 Done")
