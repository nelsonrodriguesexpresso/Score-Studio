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


def _latin_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    latin = sum("LATIN" in unicodedata.name(char, "") for char in letters)
    return latin / len(letters)


def _looks_portuguese(text: str) -> bool:
    if _latin_ratio(text) < 0.97:
        return False
    words = set(_normalise(text).split())
    clues = {
        "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
        "e", "ela", "ele", "em", "eu", "me", "meu", "minha", "na", "nao",
        "nas", "no", "nos", "o", "os", "para", "por", "que", "se", "sem",
        "sou", "te", "tem", "tu", "um", "uma", "voce",
    }
    return len(words & clues) >= 3


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
        if not lyrics or not _looks_portuguese(lyrics):
            continue
        candidate_title = _normalise(item.get("trackName", ""))
        candidate_artist = _normalise(item.get("artistName", ""))
        title_score = SequenceMatcher(None, wanted_title, candidate_title).ratio()
        item_duration = float(item.get("duration") or 0)
        duration_gap = abs(duration - item_duration) if duration and item_duration else None
        if wanted_artist:
            artist_score = SequenceMatcher(None, wanted_artist, candidate_artist).ratio()
            score = title_score * 0.72 + artist_score * 0.28
        else:
            # Sem artista, só a duração pode distinguir músicas com o mesmo título.
            if duration_gap is None or duration_gap > 4:
                continue
            score = title_score
        if duration_gap is not None and duration_gap <= 4:
            score += 0.06
        if score > best_score:
            best_score, best = score, item

    if not best or best_score < 0.82:
        return None
    return {
        "text": best["plainLyrics"].strip(),
        "segments": [],
        "language": "pt-PT",
        "source": "lrclib",
        "track": best.get("trackName"),
        "artist": best.get("artistName"),
    }
