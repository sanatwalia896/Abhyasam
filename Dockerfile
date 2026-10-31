FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    FASTEMBED_THREADS=2 SERVE_FRONTEND=false
WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
# Bake the actual model and verify it once while network access is available.
COPY backend/embedding_runtime.py ./embedding_runtime.py
RUN python embedding_runtime.py
# Runtime must use the baked files; a missing model fails instead of downloading.
ENV FASTEMBED_LOCAL_FILES_ONLY=true HF_HUB_OFFLINE=1 PORT=8080
RUN python embedding_runtime.py
COPY backend/ ./
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /opt/fastembed
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "exec python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
