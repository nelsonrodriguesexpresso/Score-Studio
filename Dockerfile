FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 curl unzip ca-certificates \
    && curl -fsSL https://deno.land/install.sh | sh \
    && mv /root/.deno/bin/deno /usr/local/bin/deno \
    && deno --version \
    && rm -rf /var/lib/apt/lists/* /root/.deno

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .
RUN mkdir -p uploads generated

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
