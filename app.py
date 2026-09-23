from fastapi import FastAPI, Request, UploadFile, File, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from pathlib import Path
from datetime import datetime
import gc
import json
import re
import traceback
import uuid
from threading import Lock
from audio_guides import generate_guide
from playback_mix import source_cache, mixer_cache, generate_mix

from analyzer import analyze_audio
from pdf_export import create_pdf
from youtube_source import download_youtube_audio, cleanup_youtube_temp, YoutubeSourceError
from mutagen import File as MutagenFile

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
GENERATED = BASE / "generated"
LOGFILE = BASE / "score_error.log"
VERSION_FILE = BASE / "VERSION.txt"
UPLOADS.mkdir(exist_ok=True)
GENERATED.mkdir(exist_ok=True)
VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "5.0.0"

app = FastAPI(title="Score Studio", version=VERSION)
guide_lock = Lock()
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


def audio_title(path, fallback: str) -> str:
    try:
        tags = MutagenFile(str(path), easy=True)
        title = str((tags.get("title") or [""])[0]).strip() if tags else ""
        artist = str((tags.get("artist") or tags.get("albumartist") or [""])[0]).strip() if tags else ""
        if title and artist:
            return f"{artist} - {title}"
        return title or fallback
    except Exception:
        return fallback


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


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), instrument: str = Form("bass5")):
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
        detected_title = audio_title(temp_path, Path(filename).stem)
        result = await run_in_threadpool(analyze_audio, temp_path, instrument)
        gc.collect()
        result["playback_token"] = await run_in_threadpool(source_cache.save, temp_path, result["audio_duration"])
        result.update({
            "ok": True,
            "title": detected_title,
            "source": "file",
            "version": VERSION,
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
async def analyze_youtube(url: str = Form(...), instrument: str = Form("bass5")):
    token = None
    try:
        if not valid_instrument(instrument):
            return JSONResponse({"ok": False, "error": "Instrumento inválido."}, status_code=400)

        audio_path, title, source_duration, token = await run_in_threadpool(
            download_youtube_audio, url, UPLOADS
        )
        result = await run_in_threadpool(analyze_audio, audio_path, instrument)
        gc.collect()
        result["playback_token"] = await run_in_threadpool(source_cache.save, audio_path, result["audio_duration"])
        result.update({
            "ok": True,
            "title": title,
            "source": "youtube",
            "source_duration": source_duration,
            "version": VERSION,
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


@app.post("/api/audio-guide")
def audio_guide(payload: dict = Body(...)):
    if not guide_lock.acquire(blocking=False):
        return JSONResponse({"ok": False, "error": "Já existe uma pista a ser gerada. Tenta novamente dentro de instantes."}, status_code=429)
    output = GENERATED / f"guide_{uuid.uuid4().hex}.wav"
    try:
        generate_guide(payload, output)
        label = "Click" if payload.get("kind") == "click" else "Guia_Voz_PT-PT"
        return FileResponse(str(output), media_type="audio/wav",
                            filename=f"{label}_{safe_filename(payload.get('title'))}.wav",
                            headers={"Cache-Control": "no-store"},
                            background=BackgroundTask(lambda: output.unlink(missing_ok=True)))
    except ValueError as exc:
        output.unlink(missing_ok=True)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception:
        output.unlink(missing_ok=True)
        log_error()
        return JSONResponse({"ok": False, "error": "Não foi possível gerar a pista de áudio. Tenta novamente."}, status_code=500)
    finally:
        guide_lock.release()


@app.post("/api/playback-mix")
def playback_mix(payload: dict = Body(...)):
    if not guide_lock.acquire(blocking=False):
        return JSONResponse({"ok": False, "error": "Existe uma pista a ser gerada. Tenta novamente dentro de instantes."}, status_code=429)
    output = GENERATED / f"mix_{uuid.uuid4().hex}.mp3"
    try:
        generate_mix(payload, output)
        return FileResponse(str(output), media_type="audio/mpeg",
                            filename=f"Mistura_{safe_filename(payload.get('title'))}.mp3",
                            headers={"Cache-Control": "no-store"},
                            background=BackgroundTask(lambda: output.unlink(missing_ok=True)))
    except ValueError as exc:
        output.unlink(missing_ok=True)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception:
        output.unlink(missing_ok=True)
        log_error()
        return JSONResponse({"ok": False, "error": "Não foi possível preparar a mistura. Tenta novamente."}, status_code=500)
    finally:
        guide_lock.release()


@app.post("/api/mixer-session")
def mixer_session(payload: dict = Body(...)):
    if not guide_lock.acquire(blocking=False):
        return JSONResponse({"error": "Existe uma pista a ser gerada. Tenta novamente dentro de instantes."}, status_code=429)
    output = GENERATED / f"desk_{uuid.uuid4().hex}.wav"
    try:
        generate_mix(payload, output, multichannel=True)
        token = mixer_cache.save(output, 0)
        if not token:
            raise ValueError("A música excede o limite da mesa de mistura.")
        return {"url": f"/api/mixer-audio/{token}"}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        log_error()
        return JSONResponse({"error": "Não foi possível preparar a mesa de mistura."}, status_code=500)
    finally:
        output.unlink(missing_ok=True)
        guide_lock.release()


@app.get("/api/mixer-audio/{token}")
def mixer_audio(token: str):
    with mixer_cache.lock:
        mixer_cache.prune()
        item = mixer_cache.entries.get(token)
        if not item:
            return JSONResponse({"error": "A sessão expirou. Prepara novamente a mesa."}, status_code=404)
        return FileResponse(str(item[0]), media_type="audio/wav", headers={"Cache-Control": "no-store"})
