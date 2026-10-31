"""One model and cache configuration for ingestion, retrieval, and image baking."""
import os
from functools import lru_cache
from fastembed import TextEmbedding

MODEL = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def embedding_model():
    return TextEmbedding(
        model_name=MODEL,
        cache_dir=os.getenv("FASTEMBED_CACHE_PATH", os.path.expanduser("~/.cache/fastembed")),
        local_files_only=os.getenv("FASTEMBED_LOCAL_FILES_ONLY", "false").lower() == "true",
        threads=int(os.getenv("FASTEMBED_THREADS", "2")),
    )


if __name__ == "__main__":
    vector = next(embedding_model().embed(["Verify the baked embedding model."]))
    assert len(vector) == 384
    print("FastEmbed loaded successfully: 384 dimensions")
