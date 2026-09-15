"""Offline rehearsal stems. Render short blocks to keep RAM bounded."""
from bisect import bisect_left
from pathlib import Path
from tempfile import TemporaryDirectory
import math
import shutil
import subprocess
import wave

import numpy as np

RATE = 22050
MAX_DURATION = 1800


def number(value, label, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label}: valor inválido.")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label}: usa um valor entre {low} e {high}.")
    return value


def prepare(payload):
    duration = number(payload.get("duration"), "Duração (segundos)", 1, MAX_DURATION)
    tempo = number(payload.get("tempo"), "BPM", 30, 300)
    meter = payload.get("meter", "4/4")
    if meter not in {"2/4", "3/4", "4/4", "6/8"}:
        raise ValueError("Compasso inválido.")
    beats_per_bar = int(meter.split("/")[0])
    offset = number(payload.get("offset", 0), "Ajuste do click", -10, 10)
    accent = number(payload.get("accent", 0), "Primeiro tempo", 0, beats_per_bar - 1)
    if not accent.is_integer():
        raise ValueError("Escolhe uma batida inteira para o primeiro tempo.")
    mode = payload.get("mode", "detected")
    if mode == "detected":
        raw = payload.get("beat_times")
        if not isinstance(raw, list) or not 2 <= len(raw) <= 20000:
            raise ValueError("Sem batidas suficientes. Escolhe o click com BPM fixo.")
        beats = [number(t, "Batida", 0, duration) for t in raw]
        if any(b - a < .05 for a, b in zip(beats, beats[1:])):
            raise ValueError("As batidas devem estar por ordem e separadas por pelo menos 0,05 s.")
    elif mode == "fixed":
        # BPM counts displayed pulses: quarter notes in x/4, eighth notes in 6/8.
        beats = np.arange(0, duration + abs(offset), 60 / tempo).tolist()
    else:
        raise ValueError("Modo de click inválido.")
    # Retain original indexes when an offset removes a beat at the start.
    clicks = [(t + offset, (i - int(accent)) % beats_per_bar == 0)
              for i, t in enumerate(beats) if 0 <= t + offset < duration]
    if not clicks:
        raise ValueError("O ajuste colocou todas as batidas fora da música.")
    return duration, clicks


def speech(text, destination):
    executable = shutil.which("espeak-ng")
    if not executable:
        raise RuntimeError("A voz PT-PT não está disponível neste servidor.")
    # 'pt' is Portugal in eSpeak NG; 'pt-br' is Brazilian Portuguese.
    subprocess.run([executable, "-v", "pt", "-s", "155", "-w", str(destination),
                    "--stdin"], input=text.lower(), text=True, encoding="utf-8",
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=10)
    with wave.open(str(destination), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise RuntimeError("Formato inesperado da voz PT-PT.")
        sound = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
    nonzero = np.flatnonzero(np.abs(sound) > .002)
    if not len(nonzero):
        raise ValueError("Não foi possível pronunciar o nome da secção.")
    sound = sound[max(0, nonzero[0] - 220):min(len(sound), nonzero[-1] + 441)]
    return sound * (.7 / max(float(np.max(np.abs(sound))), .01))


def voice_events(payload, duration, clicks, folder):
    sections = payload.get("cue_sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 128:
        raise ValueError("Adiciona entre 1 e 128 avisos de secção.")
    lead = number(payload.get("lead_beats", 4), "Antecipação", 0, 16)
    if not lead.is_integer():
        raise ValueError("A antecipação deve ser um número inteiro de batidas.")
    timed = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("Aviso de secção inválido.")
        name = section.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 60:
            raise ValueError("Cada aviso precisa de um nome com 1 a 60 caracteres.")
        name = name.strip()
        if name.upper() == "INTRO":
            name = "Introdução"
        start = number(section.get("start"), "Entrada da secção", 0, duration)
        if start >= duration:
            raise ValueError("A entrada da secção deve ser anterior ao fim da música.")
        timed.append((start, name))
    timed.sort()
    times = [t for t, _ in clicks]
    step = float(np.median(np.diff(times))) if len(times) > 1 else 60 / float(payload["tempo"])
    events, cache = [], {}
    previous_end = 0
    for start, name in timed:
        if name not in cache:
            cache[name] = speech(name, folder / "voice.wav")
        sound = cache[name]
        if lead:
            idx = bisect_left(times, start)
            target = idx - int(lead)
            at = times[target] if target >= 0 and target < len(times) else times[0] + target * step
            # Finish the announcement before the section, whenever room exists.
            at = min(at, start - len(sound) / RATE - .08)
        else:
            at = start
        at = max(0, at)
        end = at + len(sound) / RATE
        if at < previous_end or end > duration:
            raise ValueError("Os avisos ficam sobrepostos ou ultrapassam o fim. Ajusta os tempos, a antecipação ou encurta os nomes.")
        events.append((round(at * RATE), sound))
        previous_end = end
    return events


def render_wav(destination, duration, events):
    """Mix a one-second block at a time, including sounds crossing block boundaries."""
    events = sorted(events, key=lambda event: event[0])
    total = round(duration * RATE)
    cursor, active = 0, []
    with wave.open(str(destination), "wb") as wav:
        wav.setparams((1, 2, RATE, total, "NONE", "not compressed"))
        for start in range(0, total, RATE):
            end = min(start + RATE, total)
            block = np.zeros(end - start, dtype=np.float32)
            while cursor < len(events) and events[cursor][0] < end:
                active.append(events[cursor])
                cursor += 1
            for pos, sound in active:
                a, b = max(start, pos), min(end, pos + len(sound))
                if b > a:
                    block[a-start:b-start] += sound[a-pos:b-pos]
            active = [(pos, sound) for pos, sound in active if pos + len(sound) > end]
            wav.writeframesraw((np.clip(block, -1, 1) * 32767).astype("<i2").tobytes())


def generate_guide(payload, destination):
    kind = payload.get("kind")
    if kind not in {"click", "cues"}:
        raise ValueError("Escolhe click ou guia de voz.")
    duration, clicks = prepare(payload)
    with TemporaryDirectory(prefix="score-voice-") as folder:
        if kind == "click":
            t = np.arange(round(.045 * RATE)) / RATE
            envelope = np.minimum(t / .002, 1) * np.exp(-t * 100)
            normal = (.48 * np.sin(2 * np.pi * 1100 * t) * envelope).astype(np.float32)
            accent = (.72 * np.sin(2 * np.pi * 1760 * t) * envelope).astype(np.float32)
            events = [(round(at * RATE), accent if strong else normal) for at, strong in clicks]
        else:
            events = voice_events(payload, duration, clicks, Path(folder))
        render_wav(destination, duration, events)
