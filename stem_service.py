from __future__ import annotations

from pathlib import Path
import os
import uuid

from fastapi import FastAPI, File, Header, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from stem_separator import separate_audio, stem_file, StemSeparationError

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
STEMS = BASE / "generated" / "stems"
UPLOADS.mkdir(parents=True, exist_ok=True)
STEMS.mkdir(parents=True, exist_ok=True)

SERVICE_TOKEN = os.environ.get("STEM_SERVICE_TOKEN", "").strip()
MAX_UPLOAD = 120 * 1024 * 1024
ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}

app = FastAPI(title="Score Studio Stems", version="1.0")


def _authorized(value: str | None) -> bool:
    return bool(SERVICE_TOKEN) and bool(value) and value == SERVICE_TOKEN


@app.get("/api/health")
def health():
    return {"ok": True, "service": "score-studio-stems", "mode": "dedicated"}


@app.post("/api/separate")
async def separate(
    file: UploadFile = File(...),
    x_score_studio_key: str | None = Header(default=None),
):
    if not _authorized(x_score_studio_key):
        return JSONResponse({"ok": False, "error": "Não autorizado."}, status_code=401)

    filename = file.filename or "audio.wav"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        ext = ".wav"

    temp_path = UPLOADS / f"{uuid.uuid4().hex}{ext}"
    try:
        content = await file.read()
        if not content:
            return JSONResponse({"ok": False, "error": "O áudio está vazio."}, status_code=400)
        if len(content) > MAX_UPLOAD:
            return JSONResponse({"ok": False, "error": "O áudio excede o limite de 120 MB."}, status_code=400)
        temp_path.write_bytes(content)

        result = await run_in_threadpool(separate_audio, temp_path, STEMS)
        result["ok"] = True
        return JSONResponse(result)
    except StemSeparationError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": "A separação de pistas falhou.", "detail": f"{type(exc).__name__}: {exc}"},
            status_code=500,
        )
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.get("/api/stems/{token}/{stem}")
def get_stem(token: str, stem: str):
    try:
        path = stem_file(STEMS, token, stem)
        return FileResponse(
            path=str(path),
            media_type="audio/mpeg",
            filename=f"{stem}.mp3",
            headers={"Cache-Control": "private, no-store"},
        )
    except StemSeparationError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
