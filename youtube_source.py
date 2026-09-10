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
MAX_DURATION_SECONDS = 10 * 60


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


def _base_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 25,
        "retries": 2,
        "extractor_retries": 2,
    }


def _normalize_info(info):
    info = info or {}
    duration = float(info.get("duration") or 0)
    if duration and duration > MAX_DURATION_SECONDS:
        raise YoutubeSourceError("O vídeo excede o limite de 10 minutos.")
    return {
        "title": str(info.get("title") or "Música do YouTube").strip(),
        "duration": duration,
        "thumbnail": str(info.get("thumbnail") or "").strip(),
        "uploader": str(info.get("uploader") or info.get("channel") or "").strip(),
        "video_id": str(info.get("id") or "").strip(),
        "webpage_url": str(info.get("webpage_url") or "").strip(),
    }


def get_youtube_info(url: str):
    url = validate_youtube_url(url)
    options = _base_options()
    options.update({"skip_download": True})
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise YoutubeSourceError(
            "Não foi possível ler este vídeo. Pode estar privado, restrito ou bloqueado pelo YouTube."
        ) from exc
    return _normalize_info(info)


def download_youtube_audio(url: str, directory: Path):
    url = validate_youtube_url(url)
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    output_template = str(directory / f"{token}.%(ext)s")

    def match_filter(info, *, incomplete=False):
        duration = info.get("duration")
        if duration and duration > MAX_DURATION_SECONDS:
            return "O vídeo excede o limite de 10 minutos."
        return None

    options = _base_options()
    options.update({
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "match_filter": match_filter,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "192",
        }],
    })

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc)
        if "10 minutos" in message:
            raise YoutubeSourceError("O vídeo excede o limite de 10 minutos.") from exc
        raise YoutubeSourceError(
            "Não foi possível obter o áudio deste vídeo. O YouTube pode ter bloqueado o acesso, "
            "o vídeo pode ser privado/restrito ou o link pode não estar disponível."
        ) from exc

    meta = _normalize_info(info)
    wav_path = directory / f"{token}.wav"
    if not wav_path.exists():
        candidates = sorted(directory.glob(f"{token}.*"))
        if not candidates:
            raise YoutubeSourceError("O áudio do vídeo não ficou disponível para análise.")
        wav_path = candidates[0]
    return wav_path, meta, token


def cleanup_youtube_temp(directory: Path, token: str):
    for path in directory.glob(f"{token}.*"):
        try:
            path.unlink()
        except Exception:
            pass
