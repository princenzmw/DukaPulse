# Production container for DukaPulse Kiosk & Dashboard
FROM python:3.12-slim

WORKDIR /app

# Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set Hugging Face cache directory accessible to all users
ENV HOME=/tmp \
    HF_HOME=/tmp/cache/huggingface

# Install CPU torch from official PyTorch index, then install requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Bake sentence-transformers model weights into image for instant cold-start
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41')"

# Copy source code and install editable package
COPY . .
RUN pip install --no-cache-dir -e .

# Make cache writable by non-root users (Hugging Face Spaces default UID 1000)
RUN mkdir -p /tmp/cache/huggingface && chmod -R 777 /tmp/cache

EXPOSE 8000 8501

CMD ["sh", "-c", "uvicorn dukapulse.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
