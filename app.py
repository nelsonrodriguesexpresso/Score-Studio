from fastapi import FastAPI, Request, UploadFile, File, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse, PlainTextResponse
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
from youtube_source import (
    download_youtube_audio,
    cleanup_youtube_temp,
    get_youtube_info,
    YoutubeSourceError,
)
from security import (
    MAX_UPLOAD_BYTES,
    check_analysis_rate_limit,
    cleanup_old_files,
    client_ip,
)

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
GENERATED = BASE / "generated"
LOGFILE = BASE / "score_error.log"
VERSION_FILE = BASE / "VERSION.txt"
UPLOADS.mkdir(exist_ok=True)
GENERATED.mkdir(exist_ok=True)
VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "6.0.0-online"

app = FastAPI(title="Score Studio", version=VERSION)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


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


def rate_limit_response(request: Request):
    allowed, retry_after = check_analysis_rate_limit(client_ip(request))
    if allowed:
        return None
    minutes = max(1, (retry_after + 59) // 60)
    return JSONResponse(
        {
            "ok": False,
            "error": f"Limite temporário atingido. Tenta novamente dentro de cerca de {minutes} min.",
        },
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


def rights_error(rights_confirmed: bool):
    if rights_confirmed:
        return None
    return JSONResponse(
        {
            "ok": False,
            "error": "Confirma que tens autorização para analisar este conteúdo.",
        },
        status_code=400,
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    cleanup_old_files(UPLOADS, GENERATED)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"version": VERSION},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots():
    return "User-agent: *\nAllow: /\nDisallow: /api/\n"


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION, "message": "Score Studio ativo"}


@app.post("/api/youtube-info")
async def youtube_info(url: str = Form(...)):
    try:
        info = await run_in_threadpool(get_youtube_info, url)
        return JSONResponse(content=json_safe({"ok": True, **info}))
    except YoutubeSourceError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        log_error()
        return JSONResponse(
            {"ok": False, "error": "Não foi possível obter os dados deste vídeo.", "detail": f"{type(exc).__name__}: {exc}"},
            status_code=500,
        )


@app.post("/api/analyze")
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    instrument: str = Form("bass5"),
    rights_confirmed: bool = Form(False),
):
    temp_path = None
    limited = rate_limit_response(request)
    if limited:
        return limited
    denied = rights_error(rights_confirmed)
    if denied:
        return denied

    try:
        cleanup_old_files(UPLOADS, GENERATED)
        filename = file.filename or "audio.mp3"
        ext = Path(filename).suffix.lower()
        if ext not in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
            return JSONResponse(
                {"ok": False, "error": "Formato não suportado. Usa MP3, WAV, M4A, FLAC ou OGG."},
                status_code=400,
            )
        if not valid_instrument(instrument):
            return JSONResponse({"ok": False, "error": "Instrumento inválido."}, status_code=400)

        temp_path = UPLOADS / f"{uuid.uuid4().hex}{ext}"
        written = 0
        with temp_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    return JSONResponse(
                        {"ok": False, "error": "O ficheiro excede o limite público de 50 MB."},
                        status_code=400,
                    )
                out.write(chunk)
        if written == 0:
            return JSONResponse({"ok": False, "error": "O ficheiro de áudio está vazio."}, status_code=400)

        result = await run_in_threadpool(analyze_audio, temp_path, instrument)
        result.update({
            "ok": True,
            "title": Path(filename).stem,
            "artist": "",
            "source": "file",
            "version": VERSION,
        })
        return JSONResponse(content=json_safe(result))
    except Exception as exc:
        log_error()
        return JSONResponse(
            {"ok": False, "error": "A análise encontrou um problema.", "detail": f"{type(exc).__name__}: {exc}"},
            status_code=500,
        )
    finally:
        try:
            await file.close()
        except Exception:
            pass
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


@app.post("/api/analyze-youtube")
async def analyze_youtube(
    request: Request,
    url: str = Form(...),
    instrument: str = Form("bass5"),
    rights_confirmed: bool = Form(False),
):
    token = None
    limited = rate_limit_response(request)
    if limited:
        return limited
    denied = rights_error(rights_confirmed)
    if denied:
        return denied

    try:
        cleanup_old_files(UPLOADS, GENERATED)
        if not valid_instrument(instrument):
            return JSONResponse({"ok": False, "error": "Instrumento inválido."}, status_code=400)

        audio_path, meta, token = await run_in_threadpool(download_youtube_audio, url, UPLOADS)
        result = await run_in_threadpool(analyze_audio, audio_path, instrument)
        result.update({
            "ok": True,
            "title": meta.get("title") or "Música do YouTube",
            "artist": meta.get("uploader") or "",
            "source": "youtube",
            "source_duration": meta.get("duration") or 0,
            "thumbnail": meta.get("thumbnail") or "",
            "uploader": meta.get("uploader") or "",
            "video_id": meta.get("video_id") or "",
            "version": VERSION,
        })
        return JSONResponse(content=json_safe(result))
    except YoutubeSourceError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
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
        cleanup_old_files(UPLOADS, GENERATED)
        kind = payload.get("kind", "score")
        if kind not in {"score", "chart", "tab", "structure"}:
            return JSONResponse({"ok": False, "error": "Tipo de PDF inválido."}, status_code=400)
        instrument = payload.get("instrument", "bass5")
        if kind == "tab" and instrument == "piano":
            return JSONResponse({"ok": False, "error": "A exportação TAB não se aplica a Piano / Teclado."}, status_code=400)

        payload["version"] = VERSION
        title = safe_filename(payload.get("title", "Musica"))
        labels = {
            "score": "Pauta",
            "chart": "Partitura_Acordes",
            "tab": "TAB",
            "structure": "Estrutura",
        }
        label = labels[kind]
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
            {"ok": False, "error": "Não foi possível criar o PDF.", "detail": f"{type(exc).__name__}: {exc}"},
            status_code=500,
        )
