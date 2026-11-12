# Production container for DukaPulse Kiosk & Dashboard
FROM python:3.12-slim

WORKDIR /app

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set cache directories accessible to non-root users
ENV HOME=/tmp \
    FASTEMBED_CACHE_PATH=/tmp/cache/fastembed \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    TOKENIZERS_PARALLELISM=false

# Install python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Bake fastembed ONNX model into image for instant cold-starts
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2')"

# Copy source code and install editable package
COPY . .
RUN pip install --no-cache-dir -e .

# Make cache writable by non-root users
RUN mkdir -p /tmp/cache/fastembed && chmod -R 777 /tmp/cache

EXPOSE 8000 8501

CMD ["sh", "-c", "uvicorn dukapulse.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
