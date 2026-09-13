from difflib import SequenceMatcher
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import re
import unicodedata


API_URL = "https://lrclib.net/api/search"


def _clean(value: str) -> str:
    value = re.sub(r"\([^)]*(official|video|audio|lyrics?|letra|live|remaster)[^)]*\)", " ", value or "", flags=re.I)
    value = re.sub(r"\[[^]]*(official|video|audio|lyrics?|letra|live|remaster)[^]]*\]", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" -_")
    return value


def _normalise(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _title_artist(label: str) -> tuple[str, str]:
    cleaned = _clean(label)
    if " - " in cleaned:
        artist, title = cleaned.split(" - ", 1)
        return _clean(title), _clean(artist)
    return cleaned, ""


def find_lyrics(label: str, duration: float = 0) -> dict | None:
    title, artist = _title_artist(label)
    query = " ".join(part for part in (artist, title) if part)
    if len(query) < 2:
        return None
    request = Request(
        API_URL + "?" + urlencode({"q": query}),
        headers={"User-Agent": "ScoreStudio/5.4 (+https://scorestudiomusic.up.railway.app)"},
    )
    try:
        with urlopen(request, timeout=12) as response:
            candidates = json.load(response)
    except Exception:
        return None

    wanted_title, wanted_artist = _normalise(title), _normalise(artist)
    best = None
    best_score = 0.0
    for item in candidates[:20]:
        lyrics = (item.get("plainLyrics") or "").strip()
        if not lyrics:
            continue
        candidate_title = _normalise(item.get("trackName", ""))
        candidate_artist = _normalise(item.get("artistName", ""))
        title_score = SequenceMatcher(None, wanted_title, candidate_title).ratio()
        artist_score = SequenceMatcher(None, wanted_artist, candidate_artist).ratio() if wanted_artist else 0.65
        score = title_score * 0.72 + artist_score * 0.28
        item_duration = float(item.get("duration") or 0)
        if duration and item_duration and abs(duration - item_duration) <= 8:
            score += 0.08
        if score > best_score:
            best_score, best = score, item

    if not best or best_score < 0.68:
        return None
    return {
        "text": best["plainLyrics"].strip(),
        "segments": [],
        "language": "pt-PT",
        "source": "lrclib",
        "track": best.get("trackName"),
        "artist": best.get("artistName"),
    }
