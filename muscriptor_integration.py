import os
from pathlib import Path

import httpx
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

router = APIRouter()

BASE = Path(__file__).resolve().parent
WORKER_URL = os.getenv("MUSCRIPTOR_WORKER_URL", "").rstrip("/")
WORKER_KEY = os.getenv("MUSCRIPTOR_WORKER_KEY", "")
MAX_AUDIO_BYTES = 120 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
LATEST_VERSION_URL = "https://raw.githubusercontent.com/nelsonrodriguesexpresso/Score-Studio/feature/muscriptor-local-worker/VERSION.txt"


def _configured() -> bool:
    return bool(WORKER_URL and WORKER_KEY)


def _worker_headers() -> dict[str, str]:
    return {"X-Score-Studio-Key": WORKER_KEY}


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
                params={"t": str(int(__import__("time").time()))},
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


@router.post("/api/muscriptor/midi")
async def muscriptor_midi(file: UploadFile = File(...)):
    if not _configured():
        return JSONResponse(
            {"ok": False, "error": "MuScriptor ainda não está configurado."},
            status_code=503,
        )

    filename = file.filename or "audio.wav"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return JSONResponse(
            {"ok": False, "error": "Formato não suportado. Usa MP3, WAV, M4A, FLAC ou OGG."},
            status_code=400,
        )

    content = await file.read()
    if not content:
        return JSONResponse({"ok": False, "error": "O ficheiro de áudio está vazio."}, status_code=400)
    if len(content) > MAX_AUDIO_BYTES:
        return JSONResponse({"ok": False, "error": "O ficheiro excede o limite de 120 MB."}, status_code=400)

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

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(
                f"{WORKER_URL}/transcribe/midi",
                headers=_worker_headers(),
                files=files,
                data=data,
            )

        if not response.is_success:
            detail = ""
            try:
                payload = response.json()
                detail = payload.get("detail") or payload.get("error") or ""
            except Exception:
                detail = response.text[:300]
            return JSONResponse(
                {
                    "ok": False,
                    "error": detail or f"O MuScriptor respondeu com HTTP {response.status_code}.",
                },
                status_code=response.status_code if response.status_code < 600 else 502,
            )

        stem = Path(filename).stem or "transcricao"
        safe_stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in stem).strip() or "transcricao"
        return Response(
            content=response.content,
            media_type="audio/midi",
            headers={
                "Content-Disposition": f'attachment; filename="MuScriptor_{safe_stem}.mid"',
                "Cache-Control": "no-store",
            },
        )
    except httpx.TimeoutException:
        return JSONResponse(
            {
                "ok": False,
                "error": "A transcrição demorou demasiado tempo. Mantém o computador do MuScriptor ligado e tenta novamente.",
            },
            status_code=504,
        )
    except Exception:
        return JSONResponse(
            {
                "ok": False,
                "error": "Não foi possível contactar o MuScriptor no teu computador.",
            },
            status_code=502,
        )
