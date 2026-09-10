from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen
import json
import time
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
    def __init__(self, message: str, code: str = "youtube_error"):
        super().__init__(message)
        self.code = code


def validate_youtube_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise YoutubeSourceError("Indica um link do YouTube.", "invalid_url")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise YoutubeSourceError("O link do YouTube não é válido.", "invalid_url")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise YoutubeSourceError("Neste campo só são aceites links do YouTube.", "invalid_url")
    return value


def extract_video_id(url: str) -> str:
    value = validate_youtube_url(url)
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()

    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    else:
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_id:
            video_id = query_id
        else:
            parts = [part for part in parsed.path.split("/") if part]
            video_id = ""
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
                video_id = parts[1]

    video_id = "".join(ch for ch in video_id if ch.isalnum() or ch in "-_")
    if len(video_id) < 6:
        raise YoutubeSourceError("Não foi possível identificar o vídeo neste link.", "invalid_url")
    return video_id


def _base_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 25,
        "retries": 1,
        "extractor_retries": 1,
        "fragment_retries": 1,
    }


def _normalize_info(info):
    info = info or {}
    duration = float(info.get("duration") or 0)
    if duration and duration > MAX_DURATION_SECONDS:
        raise YoutubeSourceError("O vídeo excede o limite de 10 minutos.", "duration_limit")
    return {
        "title": str(info.get("title") or "Música do YouTube").strip(),
        "duration": duration,
        "thumbnail": str(info.get("thumbnail") or "").strip(),
        "uploader": str(info.get("uploader") or info.get("channel") or "").strip(),
        "video_id": str(info.get("id") or "").strip(),
        "webpage_url": str(info.get("webpage_url") or "").strip(),
    }


def _fallback_preview(url: str):
    video_id = extract_video_id(url)
    return {
        "title": "Vídeo do YouTube",
        "duration": 0,
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "uploader": "",
        "video_id": video_id,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "preview_source": "link",
    }


def get_youtube_info(url: str):
    """Obtém uma pré-visualização sem tentar descarregar o áudio."""
    url = validate_youtube_url(url)
    preview = _fallback_preview(url)
    canonical = preview["webpage_url"]
    endpoint = f"https://www.youtube.com/oembed?url={quote(canonical, safe='')}&format=json"
    request = Request(
        endpoint,
        headers={
            "User-Agent": "ScoreStudio/6.0 (+https://scorestudiomusic.up.railway.app)",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        preview.update({
            "title": str(data.get("title") or preview["title"]).strip(),
            "thumbnail": str(data.get("thumbnail_url") or preview["thumbnail"]).strip(),
            "uploader": str(data.get("author_name") or "").strip(),
            "preview_source": "oembed",
        })
    except Exception:
        pass
    return preview


def _is_bot_block(message: str) -> bool:
    value = message.lower()
    return any(
        marker in value
        for marker in (
            "confirm you're not a bot",
            "confirm you’re not a bot",
            "sign in to confirm",
            "cookies-from-browser",
            "use --cookies",
        )
    )


def _attempt_profiles(output_template, match_filter):
    """Perfis de compatibilidade, sem cookies, proxy ou credenciais pessoais."""
    return [
        {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "match_filter": match_filter,
        },
        {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": output_template,
            "match_filter": match_filter,
            "force_ipv4": True,
        },
        {
            "format": "bestaudio[ext=webm]/bestaudio/best",
            "outtmpl": output_template,
            "match_filter": match_filter,
            "force_ipv4": True,
        },
    ]


def _clear_partial_downloads(directory: Path, token: str):
    for path in directory.glob(f"{token}.*"):
        try:
            path.unlink()
        except Exception:
            pass


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

    last_error = None
    saw_bot_block = False

    for attempt_no, profile in enumerate(_attempt_profiles(output_template, match_filter), start=1):
        if attempt_no > 1:
            _clear_partial_downloads(directory, token)
            time.sleep(1.2 * (attempt_no - 1))

        options = _base_options()
        options.update(profile)
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "192",
        }]

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
            meta = _normalize_info(info)

            wav_path = directory / f"{token}.wav"
            if not wav_path.exists():
                candidates = sorted(directory.glob(f"{token}.*"))
                if not candidates:
                    raise yt_dlp.utils.DownloadError("ficheiro de áudio não criado")
                wav_path = candidates[0]

            meta["download_attempt"] = attempt_no
            return wav_path, meta, token

        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            last_error = exc
            if "10 minutos" in message:
                raise YoutubeSourceError("O vídeo excede o limite de 10 minutos.", "duration_limit") from exc
            if _is_bot_block(message):
                saw_bot_block = True
            continue

    _clear_partial_downloads(directory, token)

    if saw_bot_block:
        raise YoutubeSourceError(
            "O Score Studio tentou obter o áudio 3 vezes, mas o YouTube bloqueou o acesso automático a partir deste servidor. "
            "Podes continuar imediatamente carregando o ficheiro MP3, WAV, M4A, FLAC ou OGG.",
            "youtube_bot_block",
        ) from last_error

    raise YoutubeSourceError(
        "O Score Studio tentou obter o áudio 3 vezes, mas este vídeo não ficou disponível para análise automática. "
        "Podes continuar carregando o ficheiro de áudio.",
        "youtube_unavailable",
    ) from last_error


def cleanup_youtube_temp(directory: Path, token: str):
    for path in directory.glob(f"{token}.*"):
        try:
            path.unlink()
        except Exception:
            pass
