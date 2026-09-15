from pathlib import Path
from urllib.parse import urlparse
import base64
import os
import uuid
import hashlib
import threading

import yt_dlp


ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
MAX_DURATION_SECONDS = 15 * 60
COOKIE_ENV_NAME = "YOUTUBE_COOKIES_B64"
COOKIE_PATH = Path("/tmp/scorestudio-youtube-cookies.txt")
_COOKIE_SEED = None
_DOWNLOAD_LOCK = threading.Lock()


class YoutubeSourceError(Exception):
    pass


def validate_youtube_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise YoutubeSourceError("Indica um link do YouTube.")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise YoutubeSourceError("O link do YouTube não é válido.")

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise YoutubeSourceError("Neste campo só são aceites links do YouTube.")

    return value


def _youtube_cookiefile():
    """Materializa cookies autenticados apenas em runtime, nunca no repositório."""
    global _COOKIE_SEED
    encoded = (os.getenv(COOKIE_ENV_NAME) or "").strip()
    if not encoded:
        return None

    seed = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if _COOKIE_SEED == seed and COOKIE_PATH.is_file():
        return str(COOKIE_PATH)

    try:
        raw = base64.b64decode(encoded, validate=True)
        text = raw.decode("utf-8")
    except Exception as exc:
        raise YoutubeSourceError(
            "A autenticação YouTube configurada no servidor não é válida."
        ) from exc

    if "youtube.com" not in text or "\t" not in text:
        raise YoutubeSourceError(
            "O ficheiro de autenticação YouTube não parece estar no formato cookies.txt esperado."
        )

    COOKIE_PATH.write_text(text, encoding="utf-8")
    try:
        COOKIE_PATH.chmod(0o600)
    except Exception:
        pass
    _COOKIE_SEED = seed
    return str(COOKIE_PATH)


def download_youtube_audio(url: str, directory: Path):
    if not _DOWNLOAD_LOCK.acquire(blocking=False):
        raise YoutubeSourceError("Já existe um pedido YouTube em curso. Aguarda que termine.")
    try:
        return _download_youtube_audio(url, directory)
    finally:
        _DOWNLOAD_LOCK.release()


def _download_youtube_audio(url: str, directory: Path):
    url = validate_youtube_url(url)
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    output_template = str(directory / f"{token}.%(ext)s")
    cookiefile = _youtube_cookiefile()

    def match_filter(info, *, incomplete=False):
        duration = info.get("duration")
        if duration and duration > MAX_DURATION_SECONDS:
            return "O vídeo excede o limite de 15 minutos."
        return None

    options = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 25,
        "retries": 2,
        "extractor_retries": 2,
        "match_filter": match_filter,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
    }
    if cookiefile:
        options["cookiefile"] = cookiefile

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        lower = message.lower()
        if "15 minutos" in message:
            raise YoutubeSourceError("O vídeo excede o limite de 15 minutos.") from exc
        if "not a bot" in lower:
            raise YoutubeSourceError(
                "O YouTube bloqueou o acesso automático e exige verificação humana. "
                "Não foi possível confirmar a validade da sessão. "
                "Podes continuar a análise carregando um ficheiro de áudio."
            ) from exc
        if "sign in" in lower or "cookies-from-browser" in lower:
            raise YoutubeSourceError(
                "O YouTube não aceitou a autenticação para este vídeo. "
                "É necessário verificar a sessão da conta configurada no servidor."
            ) from exc
        raise YoutubeSourceError(
            "Não foi possível obter o áudio deste vídeo. O YouTube pode ter bloqueado o acesso, "
            "o vídeo pode ser privado/restrito ou o link pode não estar disponível."
        ) from exc

    wav_path = directory / f"{token}.wav"
    if not wav_path.exists():
        candidates = sorted(directory.glob(f"{token}.*"))
        if not candidates:
            raise YoutubeSourceError("O áudio do vídeo não ficou disponível para análise.")
        wav_path = candidates[0]

    title = str((info or {}).get("title") or "Música do YouTube").strip()
    duration = float((info or {}).get("duration") or 0)
    return wav_path, title, duration, token


def cleanup_youtube_temp(directory: Path, token: str):
    for path in directory.glob(f"{token}.*"):
        try:
            path.unlink()
        except Exception:
            pass
