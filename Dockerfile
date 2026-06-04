FROM python:3.11-slim

# System deps — poppler for pdf2image, tesseract for OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# HF Spaces runs as non-root user 1000
RUN mkdir -p /tmp/invoice_uploads /app/exports /app/chroma_db && \
    chmod -R 777 /tmp /app/exports /app/chroma_db

EXPOSE 7860

# HF Spaces expects port 7860
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "7860"]
