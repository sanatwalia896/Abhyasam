# abhyasam_rag.py

from langchain_pinecone import PineconeVectorStore
from langchain_pinecone.embeddings import PineconeEmbeddings
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain.schema import Document

from pinecone import Pinecone
import time


class AbhyasamRAG:
    def __init__(
        self,
        api_key: str,
        index_name: str = "integrated-sparse-py",
        embed_model: str = "pinecone-sparse-english-v0",
        cloud: str = "aws",
        region: str = "us-east-1",
    ):
        """
        Initialize Pinecone with integrated embeddings.
        """
        self.pc = Pinecone(api_key=api_key)
        self.index_name = index_name
        self.embed_model = embed_model
        self.cloud = cloud
        self.region = region
        self.index = self._init_index()

        # LangChain embedding wrapper for Pinecone
        self.embeddings = PineconeEmbeddings(model=self.embed_model)

        # LangChain VectorStore wrapper
        self.vectorstore = PineconeVectorStore(
            index=self.index, embedding=self.embeddings
        )

    def _init_index(self):
        """
        Create or connect to Pinecone index with server-side embedding.
        """
        if not self.pc.has_index(self.index_name):
            print(f"Creating Pinecone index {self.index_name}...")
            self.pc.create_index_for_model(
                name=self.index_name,
                cloud=self.cloud,
                region=self.region,
                embed={
                    "model": self.embed_model,
                    "field_map": {"text": "chunk_text"},
                },
            )
            time.sleep(2)
        else:
            print(f"Using existing index: {self.index_name}")

        return self.pc.Index(self.index_name)

    def upsert_documents(self, documents: list[dict], namespace: str | None = None):
        """
        Upsert Notion page chunks into Pinecone via LangChain.
        Each doc dict should look like:
        {
            "id": "unique-id",
            "chunk_text": "...",
            "metadata": {...}
        }
        """
        docs = []
        for d in documents:
            docs.append(
                Document(
                    page_content=d["chunk_text"],
                    metadata=d.get("metadata", {}),
                )
            )
        return self.vectorstore.add_documents(docs, namespace=namespace)

    def as_retriever(self, namespace: str | None = None, top_k: int = 5):
        """
        Get retriever for LangChain chains.
        """
        return self.vectorstore.as_retriever(
            search_kwargs={"k": top_k, "namespace": namespace}
        )


def build_conversational_chain(
    rag: AbhyasamRAG,
    llm,
    namespace: str | None = None,
    top_k: int = 5,
):
    """
    Build a ConversationalRetrievalChain with memory.
    """
    memory = ConversationBufferMemory(
        memory_key="chat_history", return_messages=True
    )
    retriever = rag.as_retriever(namespace=namespace, top_k=top_k)

    chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        memory=memory,
        return_source_documents=True,
    )
    return chain


# ---------------- Example usage ----------------
if __name__ == "__main__":
    from langchain_groq import ChatGroq

    PINECONE_API_KEY = "YOUR_PINECONE_API_KEY"
    GROQ_API_KEY = "YOUR_GROQ_API_KEY"

    rag = AbhyasamRAG(api_key=PINECONE_API_KEY)

    # Use Groq LLM
    llm = ChatGroq(
        model="mixtral-8x7b-32768",  # or whichever Groq model you choose
        api_key=GROQ_API_KEY,
        temperature=0,
    )

    chain = build_conversational_chain(rag, llm)

    # Upsert docs
    docs = [
        {
            "id": "page1_chunk1",
            "chunk_text": "Binary search is an efficient algorithm for finding items in sorted arrays.",
            "metadata": {"topic": "binary_search"},
        },
        {
            "id": "page2_chunk1",
            "chunk_text": "Dijkstra's algorithm finds the shortest path in a weighted graph.",
            "metadata": {"topic": "graphs"},
        },
    ]
    rag.upsert_documents(docs)

    # Ask a question
    query = "How does Dijkstra's algorithm work?"
    response = chain.run(query)
    print("Answer:", response)