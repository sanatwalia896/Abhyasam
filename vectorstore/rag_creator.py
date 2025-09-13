import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

class RagCreator:
    """Handles creating and updating vector stores in Pinecone for RevisionAI RAG."""

    def __init__(self, index_name: str = "revisionai-index", embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2", namespace: str = "revisionai"):
        """
        Initialize RagCreator with Pinecone index and embeddings.

        Args:
            index_name (str): Name of the Pinecone index.
            embeddings_model (str): Hugging Face embeddings model name.
            namespace (str): Pinecone namespace for organization.
        """
        try:
            self.pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
            self.index = self.pc.Index(index_name)
            self.embeddings = HuggingFaceEmbeddings(model_name=embeddings_model)
            self.namespace = namespace
            self.vectorstore = PineconeVectorStore(
                index=self.index,
                embedding=self.embeddings,
                namespace=self.namespace,
                text_key="text"
            )
            logger.info(f"RagCreator initialized for index: {index_name}")
        except Exception as e:
            logger.error(f"Failed to initialize RagCreator: {e}")
            raise

    def _is_index_populated(self) -> bool:
        """Check if the Pinecone index has any vectors."""
        try:
            stats = self.index.describe_index_stats()
            return stats.get('namespaces', {}).get(self.namespace, {}).get('vector_count', 0) > 0
        except Exception as e:
            logger.error(f"Error checking index population: {e}")
            return False

    def _filter_new_and_updated_pages(self, pages: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Filter pages into new and updated based on Pinecone existence and last_edited_time.

        - New: Pages not in Pinecone, edited < 3 days.
        - Updated: Pages in Pinecone, edited < 3 days.

        Returns:
            Dict with 'new_pages' and 'updated_pages'.
        """
        now = datetime.utcnow()
        new_pages = []
        updated_pages = []

        for page in pages:
            page_id = page['id']
            last_edited_str = page.get('last_edited_time')
            if not last_edited_str:
                logger.warning(f"Page {page_id} missing last_edited_time, skipping")
                continue

            try:
                last_edited = datetime.fromisoformat(last_edited_str.replace("Z", "+00:00"))
                days_diff = (now - last_edited).days

                # Check if page exists in Pinecone
                fetch_response = self.index.fetch(ids=[page_id], namespace=self.namespace)
                exists = page_id in fetch_response.get('vectors', {})

                if not exists and days_diff < 3:
                    new_pages.append(page)
                elif exists and days_diff < 3:
                    updated_pages.append(page)
            except Exception as e:
                logger.error(f"Error checking page {page_id}: {e}")
                continue

        return {'new_pages': new_pages, 'updated_pages': updated_pages}

    def create_vectorstore(self, pages: List[Dict[str, Any]], specific_page_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create or update vector store in Pinecone.

        - If specific_page_id provided, process only that page (if <3 days old).
        - If index empty, vectorize all pages.
        - Else, vectorize new and updated pages (<3 days).

        Args:
            pages (List[Dict]): List of Notion pages from loader.
            specific_page_id (Optional[str]): ID of specific page to vectorize.

        Returns:
            Dict with 'pages' (all input), 'new_pages' (vectorized new), 'updated_pages' (vectorized updated).
        """
        try:
            if specific_page_id:
                pages = [p for p in pages if p['id'] == specific_page_id]
                if not pages:
                    logger.warning(f"No page found with ID {specific_page_id}")
                    return {'pages': [], 'new_pages': [], 'updated_pages': []}
                
                # Check if specific page is <3 days old
                last_edited_str = pages[0].get('last_edited_time')
                if last_edited_str:
                    last_edited = datetime.fromisoformat(last_edited_str.replace("Z", "+00:00"))
                    if (datetime.utcnow() - last_edited).days >= 3:
                        logger.info(f"Page {specific_page_id} too old, skipping")
                        return {'pages': pages, 'new_pages': [], 'updated_pages': []}

            if not self._is_index_populated():
                logger.info("Index not populated - vectorizing all pages")
                texts = [page['content'] for page in pages if page['content'].strip()]
                metadatas = [
                    {
                        'title': page['title'],
                        'last_edited_time': page['last_edited_time'],
                        'source': 'notion',
                        'text': page['content']
                    } for page in pages if page['content'].strip()
                ]
                ids = [page['id'] for page in pages if page['content'].strip()]
                if texts:
                    self.vectorstore.add_texts(texts=texts, metadatas=metadatas, ids=ids)
                    logger.info(f"Vectorized {len(pages)} pages")
                return {'pages': pages, 'new_pages': pages, 'updated_pages': []}

            # Filter and vectorize new/updated
            filtered = self._filter_new_and_updated_pages(pages)
            new_pages = filtered['new_pages']
            updated_pages = filtered['updated_pages']

            for page_list, label in [(new_pages, "new"), (updated_pages, "updated")]:
                if page_list:
                    texts = [page['content'] for page in page_list if page['content'].strip()]
                    metadatas = [
                        {
                            'title': page['title'],
                            'last_edited_time': page['last_edited_time'],
                            'source': 'notion',
                            'text': page['content']
                        } for page in page_list if page['content'].strip()
                    ]
                    ids = [page['id'] for page in page_list if page['content'].strip()]
                    if texts:
                        self.vectorstore.add_texts(texts=texts, metadatas=metadatas, ids=ids)
                        logger.info(f"Vectorized {len(page_list)} {label} pages")

            return {'pages': pages, 'new_pages': new_pages, 'updated_pages': updated_pages}
        except Exception as e:
            logger.error(f"Error creating vector store: {e}")
            return {'pages': pages, 'new_pages': [], 'updated_pages': []}