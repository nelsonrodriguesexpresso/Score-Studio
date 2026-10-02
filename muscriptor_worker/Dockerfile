FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/tmp/huggingface \
    TRANSFORMERS_CACHE=/tmp/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install a CPU-only PyTorch first so the worker does not pull CUDA libraries.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.3"
RUN pip install --no-cache-dir "muscriptor==0.3.0"

EXPOSE 8222

CMD ["sh", "-c", "muscriptor serve --host 0.0.0.0 --port ${PORT:-8222} --model small --device cpu"]
