"""Short-lived source cache and streaming, synchronized rehearsal mix."""
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock, Timer
import secrets
import shutil
import subprocess
import time

from audio_guides import generate_guide, number


class SourceCache:
    def __init__(self, ttl=1800, max_bytes=256 * 1024 * 1024):
        self.folder = TemporaryDirectory(prefix="score-playback-")
        self.entries = OrderedDict()
        self.lock = RLock()
        self.ttl, self.max_bytes = ttl, max_bytes
        self.timer = None

    def prune(self):
        with self.lock:
            for token, (path, expires, duration) in list(self.entries.items()):
                if expires <= time.monotonic():
                    path.unlink(missing_ok=True)
                    del self.entries[token]

    def save(self, source, duration):
        with self.lock:
            self.prune()
            size = Path(source).stat().st_size
            if size > self.max_bytes:
                return None
            while self.entries and (len(self.entries) >= 32 or sum(p.stat().st_size for p, _, _ in self.entries.values()) + size > self.max_bytes):
                _, (old, _, _) = self.entries.popitem(last=False)
                old.unlink(missing_ok=True)
            token = secrets.token_urlsafe(32)
            target = Path(self.folder.name) / token
            shutil.copyfile(source, target)
            self.entries[token] = (target, time.monotonic() + self.ttl, duration)
            self.schedule_cleanup()
            return token

    def schedule_cleanup(self):
        # One timer per cache, even after repeated analyses or capacity evictions.
        if self.timer is None and self.entries:
            delay = max(.1, min(expires for _, expires, _ in self.entries.values()) - time.monotonic() + .1)
            self.timer = Timer(delay, self.cleanup)
            self.timer.daemon = True
            self.timer.start()

    def cleanup(self):
        with self.lock:
            self.timer = None
            self.prune()
            self.schedule_cleanup()

    @contextmanager
    def borrow(self, token, directory):
        if not isinstance(token, str):
            raise ValueError("Analisa novamente a música para ouvir a mistura.")
        with self.lock:
            self.prune()
            item = self.entries.get(token)
            if item is None:
                raise ValueError("O áudio temporário expirou ou já não está disponível. Analisa novamente a música.")
            path, _, duration = item
            target = Path(directory) / "source"
            shutil.copyfile(path, target)
        try:
            yield target, duration
        finally:
            target.unlink(missing_ok=True)


source_cache = SourceCache()
mixer_cache = SourceCache(max_bytes=768 * 1024 * 1024)


def generate_mix(payload, destination, multichannel=False):
    levels = [number(payload.get(key, default), key, 0, 100) / 100
              for key, default in [("music_volume", 60), ("click_volume", 80), ("cues_volume", 100)]]
    if not multichannel and not any(levels):
        raise ValueError("Aumenta o volume de pelo menos uma pista.")
    with TemporaryDirectory(prefix="score-mix-") as folder:
        folder = Path(folder)
        with source_cache.borrow(payload.get("playback_token"), folder) as (source, duration):
            data = dict(payload, duration=duration)
            number(duration, "Duração (segundos)", 1, 1800)
            generate_guide(dict(data, kind="click"), folder / "click.wav")
            generate_guide(dict(data, kind="cues"), folder / "cues.wav")
            filters = ";".join(f"[{i}:a]asetpts=PTS-STARTPTS,volume={level}[a{i}]" for i, level in enumerate(levels))
            filters += ";[a0][a1][a2]amix=inputs=3:duration=longest:normalize=0,alimiter=limit=0.95:level=0:latency=1[out]"
            if multichannel:
                filters = (f"[0:a]asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,apad,atrim=duration={duration}[music];"
                           "[1:a]asetpts=PTS-STARTPTS,aresample=44100[click];"
                           "[2:a]asetpts=PTS-STARTPTS,aresample=44100[cues];"
                           "[music][click][cues]join=inputs=3:channel_layout=quad:map=0.0-FL|0.1-FR|1.0-BL|2.0-BR[out]")
            codec = ["-ac", "4", "-channel_layout", "quad", "-c:a", "pcm_s16le"] if multichannel else ["-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k"]
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1",
                            "-i", str(source), "-i", str(folder / "click.wav"), "-i", str(folder / "cues.wav"),
                            "-filter_complex_threads", "1", "-filter_complex", filters, "-map", "[out]",
                            "-t", str(duration), "-ar", "44100", *codec,
                            str(destination)], check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
