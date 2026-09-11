from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid


STEM_IDS = ("vocals", "bass", "drums", "other")
STEM_LABELS = {
    "vocals": "Voz",
    "bass": "Baixo",
    "drums": "Bateria",
    "other": "Outros",
}
TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


class StemSeparationError(RuntimeError):
    pass


def _safe_token(token: str) -> str:
    token = str(token or "").strip().lower()
    if not TOKEN_RE.fullmatch(token):
        raise StemSeparationError("Sessão de pistas inválida.")
    return token


def cleanup_stem_session(root: Path, token: str) -> None:
    try:
        token = _safe_token(token)
    except StemSeparationError:
        return
    shutil.rmtree(Path(root) / token, ignore_errors=True)


def schedule_stem_cleanup(root: Path, token: str, seconds: int = 1800) -> None:
    timer = threading.Timer(seconds, cleanup_stem_session, args=(Path(root), token))
    timer.daemon = True
    timer.start()


def stem_file(root: Path, token: str, stem: str) -> Path:
    token = _safe_token(token)
    if stem not in STEM_IDS:
        raise StemSeparationError("Pista inválida.")
    path = Path(root) / token / f"{stem}.mp3"
    if not path.exists() or not path.is_file():
        raise StemSeparationError("A pista já não está disponível.")
    return path


def separate_audio(audio_path: Path, root: Path) -> dict:
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise StemSeparationError("O áudio temporário não está disponível.")

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    session_dir = root / token
    work_dir = session_dir / "demucs"
    session_dir.mkdir(parents=True, exist_ok=False)

    try:
        command = [
            sys.executable,
            "-m",
            "demucs.separate",
            "-n",
            "htdemucs",
            "-j",
            "1",
            "--out",
            str(work_dir),
            str(audio_path),
        ]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15 * 60,
            check=False,
        )
        if result.returncode != 0:
            tail = (result.stdout or "")[-1600:]
            raise StemSeparationError(f"A separação de pistas falhou. {tail}")

        source_dir = work_dir / "htdemucs" / audio_path.stem
        if not source_dir.exists():
            candidates = list(work_dir.glob("htdemucs/*"))
            if len(candidates) == 1 and candidates[0].is_dir():
                source_dir = candidates[0]
        if not source_dir.exists():
            raise StemSeparationError("O motor de separação não devolveu as pistas esperadas.")

        tracks = []
        for stem in STEM_IDS:
            source_wav = source_dir / f"{stem}.wav"
            if not source_wav.exists():
                raise StemSeparationError(f"A pista {STEM_LABELS[stem]} não foi criada.")

            target_mp3 = session_dir / f"{stem}.mp3"
            convert = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_wav),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "160k",
                    str(target_mp3),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5 * 60,
                check=False,
            )
            if convert.returncode != 0 or not target_mp3.exists():
                raise StemSeparationError(
                    f"Não foi possível preparar a pista {STEM_LABELS[stem]}."
                )
            tracks.append(
                {
                    "id": stem,
                    "label": STEM_LABELS[stem],
                    "url": f"/api/stems/{token}/{stem}",
                }
            )

        shutil.rmtree(work_dir, ignore_errors=True)
        schedule_stem_cleanup(root, token)
        return {
            "session": token,
            "expires_in": 1800,
            "tracks": tracks,
        }
    except subprocess.TimeoutExpired as exc:
        cleanup_stem_session(root, token)
        raise StemSeparationError("A separação de pistas demorou demasiado tempo.") from exc
    except Exception:
        cleanup_stem_session(root, token)
        raise
