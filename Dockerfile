FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ENV UPLOAD_DIR=/app/data/uploads
ENV OUTPUT_DIR=/app/data/outputs
ENV FILING_CACHE_DIR=/app/data/filings

EXPOSE 8000

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
