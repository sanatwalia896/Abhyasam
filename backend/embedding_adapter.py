"""FastEmbed adapter for the existing LangChain retriever in chatbot.py."""

from langchain_core.embeddings import Embeddings
from embedding_runtime import embedding_model


class FastEmbedLangChainAdapter(Embeddings):
    """Expose FastEmbed using LangChain's embed_documents/embed_query API."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model = embedding_model()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self.model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(self.model.embed([text])).tolist()
