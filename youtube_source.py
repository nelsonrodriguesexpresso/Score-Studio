from pathlib import Path
from urllib.parse import urlparse
import base64
import os
import uuid

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
    encoded = (os.getenv(COOKIE_ENV_NAME) or "").strip()
    if not encoded:
        return None

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
    return str(COOKIE_PATH)


def download_youtube_audio(url: str, directory: Path):
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
        # O cliente tv_downgraded usado por defeito em sessões autenticadas
        # está atualmente a devolver "The page needs to be reloaded" para
        # algumas contas. Forçar estes clientes evita esse caminho.
        options["extractor_args"] = {
            "youtube": {
                "player_client": ["default", "web_embedded"],
            }
        }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        lower = message.lower()
        if "15 minutos" in message:
            raise YoutubeSourceError("O vídeo excede o limite de 15 minutos.") from exc
        if "the page needs to be reloaded" in lower:
            raise YoutubeSourceError(
                "O YouTube recusou temporariamente o cliente autenticado. Tenta novamente dentro de instantes."
            ) from exc
        if "sign in to confirm" in lower or "not a bot" in lower or "cookies-from-browser" in lower:
            if cookiefile:
                raise YoutubeSourceError(
                    "O YouTube recusou a sessão autenticada. Os cookies podem ter expirado e precisam de ser renovados."
                ) from exc
            raise YoutubeSourceError(
                "O YouTube está a exigir autenticação para este vídeo. Configura a conta dedicada do Score Studio para o analisar."
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
