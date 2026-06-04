FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    poppler-utils \
    tesseract-ocr \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Build React frontend
RUN cd frontend && npm install && npm run build

# Create writable dirs
RUN mkdir -p /tmp/invoice_uploads /app/exports /app/chroma_db && \
    chmod -R 777 /tmp /app/exports /app/chroma_db

EXPOSE 7860

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "7860"]