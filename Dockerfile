FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SENTINEL_HOST=0.0.0.0
ENV SENTINEL_PORT=7860
ENV SENTINEL_STATE_BACKEND=sqlite

ENV HF_HOME=/app/.cache

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download and cache BAAI/bge-large-en-v1.5 in the built image
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-large-en-v1.5')"

COPY backend ./backend
COPY datasets ./datasets
COPY index.html styles.css app.js ./

EXPOSE 7860

CMD ["python", "-B", "backend/server.py"]
