from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid

import requests


STEM_IDS = ("vocals", "bass", "drums", "other")
STEM_LABELS = {
    "vocals": "Voz",
    "bass": "Baixo",
    "drums": "Bateria",
    "other": "Outros",
}
TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
CHUNK_SECONDS = 25
DEMUCS_SEGMENT_SECONDS = 2
MODEL_NAME = "6b9c2ca1"


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


def _run(command: list[str], *, timeout: int, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _split_audio(audio_path: Path, chunks_dir: Path, env: dict[str, str]) -> list[Path]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    pattern = chunks_dir / "chunk_%03d.wav"
    result = _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(audio_path),
            "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
            "-reset_timestamps", "1",
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            str(pattern),
        ],
        timeout=5 * 60,
        env=env,
    )
    chunks = sorted(chunks_dir.glob("chunk_*.wav"))
    if result.returncode != 0 or not chunks:
        print(f"[stems] ffmpeg split failed rc={result.returncode}: {(result.stdout or '')[-1200:]}", flush=True)
        raise StemSeparationError("Não foi possível preparar o áudio para separar as pistas.")
    return chunks


def _demucs_chunk(chunk: Path, out_dir: Path, env: dict[str, str], index: int) -> Path:
    result = _run(
        [
            sys.executable, "-m", "demucs.separate",
            "-n", MODEL_NAME,
            "-d", "cpu",
            "-j", "1",
            "--segment", str(DEMUCS_SEGMENT_SECONDS),
            "--overlap", "0.05",
            "--shifts", "0",
            "--out", str(out_dir),
            str(chunk),
        ],
        timeout=6 * 60,
        env=env,
    )
    if result.returncode != 0:
        tail = (result.stdout or "")[-2400:]
        print(f"[stems] {MODEL_NAME} failed rc={result.returncode} chunk={index}: {tail}", flush=True)
        if result.returncode < 0:
            raise StemSeparationError("O motor de pistas foi interrompido por falta de recursos.")
        raise StemSeparationError("A separação de pistas falhou neste bloco de áudio.")

    model_root = out_dir / MODEL_NAME
    source_dir = model_root / chunk.stem
    if not source_dir.exists():
        candidates = [p for p in model_root.glob("*") if p.is_dir()]
        if len(candidates) == 1:
            source_dir = candidates[0]
    if not source_dir.exists():
        raise StemSeparationError("O motor de separação não devolveu as pistas esperadas.")
    return source_dir


def _concat_stem(parts: list[Path], target_mp3: Path, list_file: Path, env: dict[str, str]) -> None:
    if not parts:
        raise StemSeparationError("Faltam blocos de áudio para construir uma das pistas.")
    list_file.write_text("".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8")
    result = _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-codec:a", "libmp3lame", "-b:a", "128k", str(target_mp3),
        ],
        timeout=5 * 60,
        env=env,
    )
    if result.returncode != 0 or not target_mp3.exists():
        print(f"[stems] ffmpeg concat failed rc={result.returncode}: {(result.stdout or '')[-1200:]}", flush=True)
        raise StemSeparationError("Não foi possível juntar os blocos de uma das pistas.")


def _separate_audio_remote(audio_path: Path, service_url: str, service_token: str) -> dict:
    try:
        with Path(audio_path).open("rb") as handle:
            response = requests.post(
                f"{service_url.rstrip('/')}/api/separate",
                files={"file": (Path(audio_path).name, handle, "application/octet-stream")},
                headers={"X-Score-Studio-Key": service_token},
                timeout=(20, 10 * 60),
            )
    except requests.RequestException as exc:
        raise StemSeparationError("O serviço dedicado de pistas não respondeu.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise StemSeparationError("O serviço dedicado de pistas devolveu uma resposta inválida.") from exc

    if response.status_code >= 400 or not data.get("ok"):
        raise StemSeparationError(data.get("error") or "A separação de pistas falhou.")

    base = service_url.rstrip("/")
    for track in data.get("tracks", []):
        url = str(track.get("url") or "")
        if url.startswith("/"):
            track["url"] = f"{base}{url}"
    data["remote"] = True
    return data


def _separate_audio_local(audio_path: Path, root: Path) -> dict:
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise StemSeparationError("O áudio temporário não está disponível.")

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    session_dir = root / token
    chunks_dir = session_dir / "chunks"
    work_dir = session_dir / "demucs"
    session_dir.mkdir(parents=True, exist_ok=False)

    child_env = os.environ.copy()
    child_env.update({
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "MALLOC_ARENA_MAX": "2",
    })

    try:
        chunks = _split_audio(audio_path, chunks_dir, child_env)
        stem_parts: dict[str, list[Path]] = {stem: [] for stem in STEM_IDS}

        for index, chunk in enumerate(chunks):
            chunk_out = work_dir / f"part_{index:03d}"
            source_dir = _demucs_chunk(chunk, chunk_out, child_env, index)
            for stem in STEM_IDS:
                source_wav = source_dir / f"{stem}.wav"
                if not source_wav.exists():
                    raise StemSeparationError(f"A pista {STEM_LABELS[stem]} não foi criada.")
                stem_parts[stem].append(source_wav)

        tracks = []
        for stem in STEM_IDS:
            target_mp3 = session_dir / f"{stem}.mp3"
            list_file = session_dir / f"{stem}_parts.txt"
            _concat_stem(stem_parts[stem], target_mp3, list_file, child_env)
            list_file.unlink(missing_ok=True)
            tracks.append({"id": stem, "label": STEM_LABELS[stem], "url": f"/api/stems/{token}/{stem}"})

        shutil.rmtree(chunks_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)
        schedule_stem_cleanup(root, token)
        return {"session": token, "expires_in": 1800, "tracks": tracks, "model": MODEL_NAME}
    except subprocess.TimeoutExpired as exc:
        cleanup_stem_session(root, token)
        raise StemSeparationError("A separação de pistas demorou demasiado tempo.") from exc
    except Exception:
        cleanup_stem_session(root, token)
        raise


def separate_audio(audio_path: Path, root: Path) -> dict:
    service_url = os.environ.get("STEM_SERVICE_URL", "").strip()
    service_token = os.environ.get("STEM_SERVICE_TOKEN", "").strip()
    if service_url and service_token:
        return _separate_audio_remote(Path(audio_path), service_url, service_token)
    return _separate_audio_local(Path(audio_path), Path(root))
