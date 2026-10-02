FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/tmp/huggingface \
    TRANSFORMERS_CACHE=/tmp/huggingface \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Keep torch and torchaudio on the same CPU-only release. This avoids pulling
# CUDA libraries and prevents binary-version mismatches in beat-this.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    "torch==2.11.0" "torchaudio==2.11.0"
RUN pip install --no-cache-dir "muscriptor==0.3.0"

# Railway's test container is limited to 1 GB RAM. MuScriptor 0.3.0 reserves
# a transformer KV cache for 2000 generated tokens per 5-second chunk, which
# is too large here. Reduce the generation budget for this test worker and
# explicitly return glibc heap pages after each chunk. This patch is isolated
# to the worker image and does not touch the main Score Studio application.
RUN python - <<'PY'
from pathlib import Path
import muscriptor.transcription_model as tm

p = Path(tm.__file__)
s = p.read_text()
old_budget = "        max_gen_len = 2000"
new_budget = "        max_gen_len = 800"
if old_budget not in s:
    raise SystemExit(f"MuScriptor patch failed: {old_budget!r} not found in {p}")
s = s.replace(old_budget, new_budget, 1)

old_anchor = "            yield ProgressEvent(completed=batch_start + n, total=num_chunks)"
new_anchor = '''            yield ProgressEvent(completed=batch_start + n, total=num_chunks)\n\n            # Low-memory CPU worker: release Python objects and return free\n            # glibc heap pages between 5-second chunks.\n            if self._device.type == "cpu":\n                import gc\n                import ctypes\n                gc.collect()\n                try:\n                    ctypes.CDLL("libc.so.6").malloc_trim(0)\n                except Exception:\n                    pass'''
if old_anchor not in s:
    raise SystemExit(f"MuScriptor patch failed: progress anchor not found in {p}")
s = s.replace(old_anchor, new_anchor, 1)
p.write_text(s)
print(f"Patched {p}: max_gen_len=800 + CPU heap trim")
PY

WORKDIR /app
COPY start.py /app/start.py

EXPOSE 8222

CMD ["python", "/app/start.py"]
