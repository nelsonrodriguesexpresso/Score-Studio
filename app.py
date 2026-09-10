from fastapi import FastAPI, Request, UploadFile, File, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from pathlib import Path
from datetime import datetime
import json
import re
import traceback
import uuid

from analyzer import analyze_audio
from pdf_export import create_pdf

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "uploads"
GENERATED = BASE / "generated"
LOGFILE = BASE / "score_error.log"
VERSION_FILE = BASE / "VERSION.txt"
UPLOADS.mkdir(exist_ok=True)
GENERATED.mkdir(exist_ok=True)
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


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"version": VERSION},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


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
        if instrument not in {"bass5", "guitar", "piano"}:
            return JSONResponse({"ok": False, "error": "Instrumento inválido."}, status_code=400)

        content = await file.read()
        if not content:
            return JSONResponse({"ok": False, "error": "O ficheiro de áudio está vazio."}, status_code=400)
        if len(content) > 120 * 1024 * 1024:
            return JSONResponse({"ok": False, "error": "O ficheiro excede o limite de 120 MB."}, status_code=400)

        temp_path = UPLOADS / f"{uuid.uuid4().hex}{ext}"
        temp_path.write_bytes(content)
        result = analyze_audio(temp_path, instrument)
        result.update({
            "ok": True,
            "title": Path(filename).stem,
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
                "log": "Foi criado o ficheiro score_error.log na pasta do Score.",
            },
            status_code=500,
        )
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


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
