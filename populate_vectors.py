import os
import time
from pathlib import Path
from dotenv import load_dotenv

# Notion loader
from notion_loader import NotionPageLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import os
# Pinecone + LangChain
from pinecone import Pinecone, ServerlessSpec
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone
from dotenv import load_dotenv
load_dotenv()
from uuid import uuid4
from langchain_core.documents import Document
from langchain_pinecone import PineconeVectorStore
from langchain_huggingface import HuggingFaceEndpointEmbeddings
# model = "sentence-transformers/all-mpnet-base-v2"
# hf_embeddings = HuggingFaceEndpointEmbeddings(
#     model=model,
#     task="feature-extraction",
#     huggingfacehub_api_token=os.environ.get("HUGGINGFACE_TOKEN"),
# )
# if not pc.has_index(index_name):
#     pc.create_index(
#         name=index_name,
#         dimension=768,
#         metric="cosine",
#         spec=ServerlessSpec(cloud="aws", region="us-east-1"),
#     )

# index = pc.Index(index_name)

# ---------------- RAG Wrapper ----------------
class AbhyasamRAG:
    def __init__(
        self,
        api_key: str,
        index_name: str = "abhyasam-index",
        cloud: str = "aws",
        region: str = "us-east-1",
        namespace: str = "notion-knowledge",
    ):
        """Initialize Pinecone with HuggingFace embeddings."""
        self.pc = Pinecone(api_key=api_key)
        self.index_name = index_name
        self.cloud = cloud
        self.region = region
        self.namespace = namespace

        self.embeddings = HuggingFaceEndpointEmbeddings(
            model = "sentence-transformers/all-mpnet-base-v2",
            task="feature-extraction",
            huggingfacehub_api_token=os.environ.get("HUGGINGFACE_TOKEN")
        )

        if not self.pc.has_index(self.index_name):
            self.pc.create_index(
                name=self.index_name,
                dimension=768,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
        
        self.index=self.pc.Index(index_name)
        self.vector_store = PineconeVectorStore(index=self.index, embedding=self.embeddings)


    def upsert_documents(self, documents: list[Document], namespace: str | None = None):
        """Upsert Notion page chunks into Pinecone via LangChain VectorStore."""
        uuids = [str(uuid4()) for _ in range(len(documents))]
        self.vector_store.add_documents(documents=documents, ids=uuids,namespace=namespace)
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
