from pathlib import Path
from urllib.parse import urlparse
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


def download_youtube_audio(url: str, directory: Path):
    url = validate_youtube_url(url)
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    output_template = str(directory / f"{token}.%(ext)s")

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

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        if "15 minutos" in message:
            raise YoutubeSourceError("O vídeo excede o limite de 15 minutos.") from exc
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
