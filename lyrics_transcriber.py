from pathlib import Path
import json
import os
import subprocess
import sys


class LyricsTranscriptionError(RuntimeError):
    pass


def transcribe_lyrics(audio_path: Path) -> dict:
    env = os.environ.copy()
    env.update({
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "MALLOC_ARENA_MAX": "2",
    })
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("lyrics_worker.py")), str(audio_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15 * 60,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise LyricsTranscriptionError("A transcrição da letra demorou demasiado tempo.") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "")[-800:].strip()
        raise LyricsTranscriptionError(detail or "Não foi possível transcrever a letra.")

    try:
        data = json.loads((result.stdout or "").strip().splitlines()[-1])
    except Exception as exc:
        raise LyricsTranscriptionError("O motor de letra devolveu uma resposta inválida.") from exc

    if not data.get("text"):
        raise LyricsTranscriptionError("Não foi possível distinguir uma voz cantada neste áudio.")
    return data
