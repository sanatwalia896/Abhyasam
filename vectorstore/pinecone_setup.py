import os
from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

def setup_pinecone_index():
    """Set up a Pinecone index for RevisionAI."""
    try:
        # Initialize Pinecone client
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        
        # Define index name and specs
        index_name = "revisionai-index"
        dimension = 384  # Matches all-MiniLM-L6-v2
        metric = "cosine"
        
        # Check if index exists, create if not
        if index_name not in pc.list_indexes().names():
            logger.info(f"Creating Pinecone index: {index_name}")
            pc.create_index(
                name=index_name,
                dimension=dimension,
                metric=metric,
                spec=ServerlessSpec(
                    cloud="aws",
                    region=os.getenv("PINECONE_ENVIRONMENT")
                )
            )
            logger.info(f"Index {index_name} created successfully")
        else:
            logger.info(f"Index {index_name} already exists")
        
        # Connect to the index
        index = pc.Index(index_name)
        return index
    except Exception as e:
        logger.error(f"Failed to set up Pinecone index: {e}")
        raise

if __name__ == "__main__":
    index = setup_pinecone_index()
    logger.info(f"Connected to index: {index.describe_index_stats()}")