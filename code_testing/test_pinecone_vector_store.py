from pinecone import Pinecone, ServerlessSpec
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
import os
from langchain_groq import ChatGroq
from langchain_core.runnables import RunnableParallel
from dotenv import load_dotenv
load_dotenv()

class PineconeVector:
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

        # Debug: Print index stats
        index = self.pc.Index(self.index_name)
        print("Index stats:", index.describe_index_stats())

pine_vector = PineconeVector(api_key=os.getenv("PINECONE_API_KEY"))

# Updated retriever: Increase k to 9, add low score_threshold for more/weaker matches
retriever = pine_vector.vector_store.as_retriever(
    search_kwargs={"k": 9, "score_threshold": 0.8}  # Fetches up to 9 with min score 0.3
)

# Test with your query
query = "what is model context protocol ?"
result = retriever.invoke(query,filter={"source": "Notion"})

# # Print with scores (LangChain adds score to metadata if available)
# print("Retrieved docs:")
# if result:
#     for doc in result:
#         score = doc.metadata.get('score', 'N/A')  # Cosine score from Pinecone
#         print(f"Content: {doc.page_content[:100]}... | Score: {score} | ID: {doc.metadata.get('id', 'N/A')}")
# else:
#     print("Still empty? Try even lower threshold (e.g., 0.1) or add more MCP content.")

# Optional: Enhance the MCP chunk for better matching (add fuller text)
# pine_vector.vector_store.add_texts(
#     texts=["Model Context Protocol (MCP) is an open standard by Anthropic for connecting AI models to external tools and data sources, ensuring compliance with data protection regulations and clear boundaries between shared and private context."],
#     metadatas=[{"source": "enhanced_mcp"}]
# )
# Then re-run the query above.

print(result)

# # Your original debug fetch (keep for verification)
# index = pine_vector.pc.Index(pine_vector.index_name)
# results = index.query(
#     vector=[0] * 384,  # Dummy vector to get all
#     top_k=9,
#     include_metadata=True,
#     namespace='rag'
# )
# print("\nStored documents:")
# for match in results['matches']:
#     print(f"ID: {match['id']}, Metadata: {match.get('metadata', {})}")