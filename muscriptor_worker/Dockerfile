FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/tmp/huggingface \
    TRANSFORMERS_CACHE=/tmp/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Keep torch and torchaudio on the same CPU-only release. This avoids pulling
# CUDA libraries and prevents binary-version mismatches in beat-this.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    "torch==2.11.0" "torchaudio==2.11.0"
RUN pip install --no-cache-dir "muscriptor==0.3.0"

WORKDIR /app
COPY start.py /app/start.py

EXPOSE 8222

CMD ["python", "/app/start.py"]
