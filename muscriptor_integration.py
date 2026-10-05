import base64
import json
import os
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

router = APIRouter()

BASE = Path(__file__).resolve().parent
WORKER_URL = os.getenv("MUSCRIPTOR_WORKER_URL", "").rstrip("/")
WORKER_KEY = os.getenv("MUSCRIPTOR_WORKER_KEY", "")
MAX_AUDIO_BYTES = 120 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
LATEST_VERSION_URL = "https://raw.githubusercontent.com/nelsonrodriguesexpresso/Score-Studio/feature/muscriptor-local-worker/VERSION.txt"

_progress_jobs: dict[str, dict] = {}


def _configured() -> bool:
    return bool(WORKER_URL and WORKER_KEY)


def _worker_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"X-Score-Studio-Key": WORKER_KEY}
    if extra:
        headers.update(extra)
    return headers


def _current_version() -> str:
    try:
        return (BASE / "VERSION.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except Exception:
        return (0,)


def _set_progress(job_id: str, **values) -> None:
    if not job_id:
        return
    current = _progress_jobs.get(job_id, {})
    current.update(values)
    current["job_id"] = job_id
    current["updated_at"] = time.time()
    _progress_jobs[job_id] = current
    if len(_progress_jobs) > 120:
        stale = sorted(_progress_jobs.items(), key=lambda item: item[1].get("updated_at", 0))[:20]
        for key, _ in stale:
            _progress_jobs.pop(key, None)


@router.get("/manifest.webmanifest", include_in_schema=False)
def pwa_manifest():
    return FileResponse(
        BASE / "static" / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/service-worker.js", include_in_schema=False)
def pwa_service_worker():
    return FileResponse(
        BASE / "static" / "service-worker.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


@router.get("/api/update-status")
async def update_status():
    current = _current_version()
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            response = await client.get(
                LATEST_VERSION_URL,
                headers={"Cache-Control": "no-cache"},
                params={"t": str(int(time.time()))},
            )
        response.raise_for_status()
        latest = response.text.strip()
        return {
            "ok": True,
            "current_version": current,
            "latest_version": latest,
            "update_available": _version_tuple(latest) > _version_tuple(current),
        }
    except Exception:
        return JSONResponse(
            {
                "ok": False,
                "current_version": current,
                "latest_version": None,
                "update_available": False,
                "error": "Não foi possível verificar atualizações neste momento.",
            },
            status_code=503,
        )


@router.get("/api/muscriptor/health")
async def muscriptor_health():
    if not _configured():
        return JSONResponse(
            {"ok": False, "online": False, "error": "MuScriptor ainda não está configurado."},
            status_code=503,
        )

    try:
        timeout = httpx.Timeout(8.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(f"{WORKER_URL}/health")
        if response.is_success:
            return {"ok": True, "online": True, "message": "MuScriptor disponível"}
        return JSONResponse(
            {
                "ok": False,
                "online": False,
                "error": f"MuScriptor respondeu com HTTP {response.status_code}.",
            },
            status_code=503,
        )
    except Exception:
        return JSONResponse(
            {
                "ok": False,
                "online": False,
                "error": "O computador do MuScriptor está desligado ou indisponível.",
            },
            status_code=503,
        )


@router.get("/api/muscriptor/progress/{job_id}")
def muscriptor_progress(job_id: str):
    item = _progress_jobs.get(job_id)
    if not item:
        return JSONResponse(
            {
                "ok": False,
                "job_id": job_id,
                "percent": 1,
                "ai_percent": 0,
                "stage": "waiting",
                "stage_label": "A preparar",
                "message": "A aguardar o início da transcrição…",
            },
            status_code=404,
        )
    return {"ok": item.get("stage") != "error", **item}


@router.post("/api/muscriptor/midi")
async def muscriptor_midi(
    file: UploadFile = File(...),
    job_id: str = Form(""),
    client_id: str = Form(""),
):
    job_id = (job_id or uuid.uuid4().hex).strip()[:120]
    client_id = (client_id or job_id).strip()[:120]
    _set_progress(
        job_id,
        percent=1,
        ai_percent=0,
        stage="uploading",
        stage_label="A preparar",
        message="A receber o ficheiro de áudio…",
    )

    if not _configured():
        _set_progress(job_id, percent=0, stage="error", stage_label="Erro", message="MuScriptor ainda não está configurado.")
        return JSONResponse(
            {"ok": False, "error": "MuScriptor ainda não está configurado."},
            status_code=503,
        )

    filename = file.filename or "audio.wav"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        _set_progress(job_id, percent=0, stage="error", stage_label="Erro", message="Formato não suportado.")
        return JSONResponse(
            {"ok": False, "error": "Formato não suportado. Usa MP3, WAV, M4A, FLAC ou OGG."},
            status_code=400,
        )

    content = await file.read()
    if not content:
        _set_progress(job_id, percent=0, stage="error", stage_label="Erro", message="O ficheiro de áudio está vazio.")
        return JSONResponse({"ok": False, "error": "O ficheiro de áudio está vazio."}, status_code=400)
    if len(content) > MAX_AUDIO_BYTES:
        _set_progress(job_id, percent=0, stage="error", stage_label="Erro", message="O ficheiro excede o limite de 120 MB.")
        return JSONResponse({"ok": False, "error": "O ficheiro excede o limite de 120 MB."}, status_code=400)

    _set_progress(
        job_id,
        percent=4,
        ai_percent=0,
        stage="queued",
        stage_label="A iniciar",
        message="Áudio recebido · a iniciar o modelo de IA…",
    )

    try:
        timeout = httpx.Timeout(connect=15.0, read=3600.0, write=180.0, pool=15.0)
        files = {
            "file": (
                filename,
                content,
                file.content_type or "application/octet-stream",
            )
        }
        data = {"detect_tempo": "best-effort"}
        midi_bytes: bytes | None = None

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream(
                "POST",
                f"{WORKER_URL}/transcribe",
                headers=_worker_headers({"X-Client-ID": client_id}),
                files=files,
                data=data,
            ) as response:
                if not response.is_success:
                    raw = (await response.aread()).decode("utf-8", errors="replace")[:500]
                    detail = raw
                    try:
                        payload = json.loads(raw)
                        detail = payload.get("detail") or payload.get("error") or raw
                    except Exception:
                        pass
                    if response.status_code == 503 and "server busy" in (detail or "").lower():
                        detail = "Existe uma transcrição anterior ainda ativa. Aguarda alguns segundos e volta a carregar em Gerar MIDI com IA."
                    _set_progress(job_id, percent=0, stage="error", stage_label="Erro", message=detail or f"HTTP {response.status_code}")
                    return JSONResponse(
                        {"ok": False, "error": detail or f"O MuScriptor respondeu com HTTP {response.status_code}."},
                        status_code=response.status_code if response.status_code < 600 else 502,
                    )

                _set_progress(
                    job_id,
                    percent=5,
                    ai_percent=0,
                    stage="transcribing",
                    stage_label="Leitura IA",
                    message="O MuScriptor está a ler a música…",
                )

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw_payload = line[5:].strip()
                    if not raw_payload:
                        continue
                    try:
                        payload = json.loads(raw_payload)
                    except Exception:
                        continue

                    kind = payload.get("type")
                    if kind == "progress":
                        completed = int(payload.get("completed") or 0)
                        total = max(1, int(payload.get("total") or 1))
                        ai_percent = max(0, min(100, round(completed * 100 / total)))
                        overall = min(95, 5 + round(ai_percent * 0.90))
                        if ai_percent >= 100:
                            _set_progress(
                                job_id,
                                percent=95,
                                ai_percent=100,
                                completed=completed,
                                total=total,
                                stage="finalizing",
                                stage_label="A finalizar",
                                message="Leitura IA concluída · a criar o MIDI e a detetar o tempo…",
                            )
                        else:
                            _set_progress(
                                job_id,
                                percent=overall,
                                ai_percent=ai_percent,
                                completed=completed,
                                total=total,
                                stage="transcribing",
                                stage_label="Leitura IA",
                                message=f"A transcrever a música… {ai_percent}%",
                            )
                    elif kind == "transcription_complete":
                        encoded = payload.get("data") or ""
                        if encoded:
                            midi_bytes = base64.b64decode(encoded)
                        _set_progress(
                            job_id,
                            percent=99,
                            ai_percent=100,
                            stage="finalizing",
                            stage_label="A finalizar",
                            message="MIDI criado · a preparar o download e a visualização…",
                        )

        if not midi_bytes:
            _set_progress(job_id, percent=0, stage="error", stage_label="Erro", message="A IA terminou sem devolver um ficheiro MIDI.")
            return JSONResponse(
                {"ok": False, "error": "A IA terminou sem devolver um ficheiro MIDI."},
                status_code=502,
            )

        stem = Path(filename).stem or "transcricao"
        safe_stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in stem).strip() or "transcricao"
        _set_progress(
            job_id,
            percent=100,
            ai_percent=100,
            stage="done",
            stage_label="Concluído",
            message="Transcrição concluída · MIDI pronto",
        )
        return Response(
            content=midi_bytes,
            media_type="audio/midi",
            headers={
                "Content-Disposition": f'attachment; filename="MuScriptor_{safe_stem}.mid"',
                "Cache-Control": "no-store",
                "X-MuScriptor-Job": job_id,
            },
        )
    except httpx.TimeoutException:
        _set_progress(job_id, percent=0, stage="error", stage_label="Erro", message="A transcrição demorou demasiado tempo.")
        return JSONResponse(
            {
                "ok": False,
                "error": "A transcrição demorou demasiado tempo. Mantém o computador do MuScriptor ligado e tenta novamente.",
            },
            status_code=504,
        )
    except Exception as exc:
        _set_progress(job_id, percent=0, stage="error", stage_label="Erro", message=f"Não foi possível contactar o MuScriptor: {type(exc).__name__}")
        return JSONResponse(
            {
                "ok": False,
                "error": "Não foi possível contactar o MuScriptor no teu computador.",
            },
            status_code=502,
        )