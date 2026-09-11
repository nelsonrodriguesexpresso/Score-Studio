from fastapi import FastAPI, Request, UploadFile, File, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from pathlib import Path
from datetime import datetime
import json
import re
import traceback
import uuid

from analyzer import analyze_audio
from pdf_export import create_pdf
from youtube_source import download_youtube_audio, cleanup_youtube_temp, YoutubeSourceError
from stem_separator import separate_audio, stem_file, StemSeparationError

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
GENERATED = BASE / "generated"
STEMS = GENERATED / "stems"
LOGFILE = BASE / "score_error.log"
VERSION_FILE = BASE / "VERSION.txt"
UPLOADS.mkdir(exist_ok=True)
GENERATED.mkdir(exist_ok=True)
STEMS.mkdir(parents=True, exist_ok=True)
VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "5.0.0"

app = FastAPI(title="Score Studio", version=VERSION)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


def log_error():
    try:
        LOGFILE.write_text(
            f"[{datetime.now().isoformat(timespec='seconds')}]\n{traceback.format_exc()}",
            encoding="utf-8",
        )
    except Exception:
        pass


def json_safe(obj):
    return json.loads(
        json.dumps(
            obj,
            ensure_ascii=False,
            default=lambda x: x.item() if hasattr(x, "item") else str(x),
        )
    )


def safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\-. ()]+", "_", str(value or "Musica"), flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return value[:100] or "Musica"


def valid_instrument(instrument: str) -> bool:
    return instrument in {"bass5", "guitar", "piano"}


async def maybe_create_stems(audio_path: Path, enabled: bool) -> tuple[dict | None, str | None]:
    if not enabled:
        return None, None
    try:
        stems = await run_in_threadpool(separate_audio, audio_path, STEMS)
        return stems, None
    except StemSeparationError as exc:
        return None, str(exc)
    except Exception as exc:
        log_error()
        return None, f"{type(exc).__name__}: {exc}"


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"version": VERSION},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(
        path=str(BASE / "static" / "favicon.svg"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION, "message": "Score Studio ativo"}


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


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    instrument: str = Form("bass5"),
    separate_stems: bool = Form(False),
):
    temp_path = None
    try:
        filename = file.filename or "audio.mp3"
        ext = Path(filename).suffix.lower()
        if ext not in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
            return JSONResponse(
                {"ok": False, "error": "Formato não suportado. Usa MP3, WAV, M4A, FLAC ou OGG."},
                status_code=400,
            )
        if not valid_instrument(instrument):
            return JSONResponse({"ok": False, "error": "Instrumento inválido."}, status_code=400)

        content = await file.read()
        if not content:
            return JSONResponse({"ok": False, "error": "O ficheiro de áudio está vazio."}, status_code=400)
        if len(content) > 120 * 1024 * 1024:
            return JSONResponse({"ok": False, "error": "O ficheiro excede o limite de 120 MB."}, status_code=400)

        temp_path = UPLOADS / f"{uuid.uuid4().hex}{ext}"
        temp_path.write_bytes(content)
        result = await run_in_threadpool(analyze_audio, temp_path, instrument)
        stems, stems_error = await maybe_create_stems(temp_path, separate_stems)
        result.update({
            "ok": True,
            "title": Path(filename).stem,
            "source": "file",
            "version": VERSION,
            "stems": stems,
            "stems_error": stems_error,
        })
        return JSONResponse(content=json_safe(result))
    except Exception as exc:
        log_error()
        return JSONResponse(
            {
                "ok": False,
                "error": "A análise encontrou um problema.",
                "detail": f"{type(exc).__name__}: {exc}",
            },
            status_code=500,
        )
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


@app.post("/api/analyze-youtube")
async def analyze_youtube(
    url: str = Form(...),
    instrument: str = Form("bass5"),
    separate_stems: bool = Form(False),
):
    token = None
    try:
        if not valid_instrument(instrument):
            return JSONResponse({"ok": False, "error": "Instrumento inválido."}, status_code=400)

        audio_path, title, source_duration, token = await run_in_threadpool(
            download_youtube_audio, url, UPLOADS
        )
        result = await run_in_threadpool(analyze_audio, audio_path, instrument)
        stems, stems_error = await maybe_create_stems(audio_path, separate_stems)
        result.update({
            "ok": True,
            "title": title,
            "source": "youtube",
            "source_duration": source_duration,
            "version": VERSION,
            "stems": stems,
            "stems_error": stems_error,
        })
        return JSONResponse(content=json_safe(result))
    except YoutubeSourceError as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc)},
            status_code=400,
        )
    except Exception as exc:
        log_error()
        return JSONResponse(
            {
                "ok": False,
                "error": "Não foi possível analisar este link do YouTube.",
                "detail": f"{type(exc).__name__}: {exc}",
            },
            status_code=500,
        )
    finally:
        if token:
            cleanup_youtube_temp(UPLOADS, token)


@app.post("/api/export")
def export_pdf(payload: dict = Body(...)):
    try:
        kind = payload.get("kind", "score")
        if kind not in {"score", "chart"}:
            return JSONResponse({"ok": False, "error": "Tipo de PDF inválido."}, status_code=400)

        payload["version"] = VERSION
        title = safe_filename(payload.get("title", "Musica"))
        label = "Pauta" if kind == "score" else "Partitura_Acordes"
        output = GENERATED / f"{label}_{uuid.uuid4().hex[:8]}.pdf"
        create_pdf(payload, output, kind)

        return FileResponse(
            path=str(output),
            media_type="application/pdf",
            filename=f"{label}_{title}.pdf",
            background=BackgroundTask(lambda: output.unlink(missing_ok=True)),
        )
    except Exception as exc:
        log_error()
        return JSONResponse(
            {
                "ok": False,
                "error": "Não foi possível criar o PDF.",
                "detail": f"{type(exc).__name__}: {exc}",
            },
            status_code=500,
        )
