from pathlib import Path
import numpy as np
import librosa
from scipy.signal import butter, sosfiltfilt

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def estimate_key(chroma):
    vector = np.nan_to_num(np.mean(chroma, axis=1), nan=0.0)
    vector /= np.linalg.norm(vector) + 1e-9
    best = (-999.0, "C")
    for root in range(12):
        for profile, suffix in ((MAJOR_PROFILE, ""), (MINOR_PROFILE, "m")):
            p = np.roll(profile, root)
            p /= np.linalg.norm(p)
            score = float(vector @ p)
            if score > best[0]:
                best = (score, NOTE_NAMES[root] + suffix)
    return best[1]


def build_chord_templates():
    templates, names = [], []
    qualities = {
        "": [(0, 1.0), (4, 0.90), (7, 0.82)],
        "m": [(0, 1.0), (3, 0.90), (7, 0.82)],
        "7": [(0, 1.0), (4, 0.86), (7, 0.80), (10, 0.55)],
        "m7": [(0, 1.0), (3, 0.87), (7, 0.80), (10, 0.50)],
    }
    for root in range(12):
        for suffix, intervals in qualities.items():
            v = np.zeros(12)
            for interval, weight in intervals:
                v[(root + interval) % 12] = weight
            templates.append(v / (np.linalg.norm(v) + 1e-9))
            names.append(NOTE_NAMES[root] + suffix)
    return np.array(templates), names


CHORD_TEMPLATES, CHORD_NAMES = build_chord_templates()


def chord_scores(vector):
    vector = np.nan_to_num(vector, nan=0.0)
    vector = vector / (np.linalg.norm(vector) + 1e-9)
    scores = CHORD_TEMPLATES @ vector
    for i, name in enumerate(CHORD_NAMES):
        if name.endswith("m7"):
            scores[i] -= 0.075
        elif name.endswith("7"):
            scores[i] -= 0.055
    return scores


def smooth_chords(score_rows):
    if not score_rows:
        return []
    obs = np.asarray(score_rows)
    n_time, n_chords = obs.shape
    dp = np.full((n_time, n_chords), -1e9)
    back = np.zeros((n_time, n_chords), dtype=int)
    dp[0] = obs[0]
    for t in range(1, n_time):
        for c in range(n_chords):
            transitions = dp[t - 1] - 0.12
            transitions[c] += 0.12
            prev = int(np.argmax(transitions))
            dp[t, c] = obs[t, c] + transitions[prev]
            back[t, c] = prev
    idx = int(np.argmax(dp[-1]))
    path = [idx]
    for t in range(n_time - 1, 0, -1):
        idx = int(back[t, idx])
        path.append(idx)
    path.reverse()
    return [CHORD_NAMES[i] for i in path]


def _rms_energy(y):
    if y is None or len(y) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(np.asarray(y, dtype=float))) + 1e-12))


def _filter_signal(y, sr, low=None, high=None):
    nyq = sr / 2.0
    if low and high:
        sos = butter(4, [max(10.0, low) / nyq, min(high, nyq - 50.0) / nyq], btype="bandpass", output="sos")
    elif high:
        sos = butter(4, min(high, nyq - 50.0) / nyq, btype="lowpass", output="sos")
    elif low:
        sos = butter(4, max(10.0, low) / nyq, btype="highpass", output="sos")
    else:
        return y
    try:
        return sosfiltfilt(sos, y).astype(np.float32, copy=False)
    except Exception:
        return y


def separate_sources(y, sr):
    """Lightweight source-focus stage for public deployment.

    HPSS separates percussion from harmonic content. Fast frequency filters then
    create approximate bass, voice-band and accompaniment focuses without the
    memory cost of a neural stem model.
    """
    harmonic, drums = librosa.effects.hpss(y, margin=(1.0, 2.0))
    bass = _filter_signal(harmonic, sr, high=360.0)
    voice_band = _filter_signal(harmonic, sr, low=120.0, high=3600.0)
    guitar_band = _filter_signal(harmonic, sr, low=75.0, high=5200.0)
    accompaniment = harmonic - 0.70 * bass
    energies = {
        "bass": round(_rms_energy(bass), 5),
        "drums": round(_rms_energy(drums), 5),
        "voice_band": round(_rms_energy(voice_band), 5),
        "accompaniment": round(_rms_energy(accompaniment), 5),
    }
    return {
        "harmonic": harmonic,
        "drums": drums,
        "bass": bass,
        "voice_band": voice_band,
        "guitar_band": guitar_band,
        "accompaniment": accompaniment,
        "energies": energies,
    }


def instrument_focus(stems, instrument):
    if instrument == "bass5":
        return stems["bass"], "Baixo"
    if instrument == "guitar":
        return stems["guitar_band"], "Guitarra"
    return stems["harmonic"], "Piano / Teclado"


def bar_rows_and_times(chroma, beat_frames, sr, duration):
    rows, times = [], []
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    if len(beat_frames) >= 8:
        for i in range(0, len(beat_frames) - 4, 4):
            start_frame = int(beat_frames[i])
            end_frame = int(beat_frames[min(i + 4, len(beat_frames) - 1)])
            if end_frame <= start_frame:
                continue
            rows.append(np.mean(chroma[:, start_frame:end_frame], axis=1))
            start_t = float(beat_times[i])
            end_t = float(beat_times[min(i + 4, len(beat_times) - 1)])
            times.append((start_t, max(start_t + 0.2, end_t)))
    return rows, times


def uniform_bar_rows(chroma, duration, tempo):
    seconds_per_bar = 240.0 / max(tempo, 1.0)
    bars = max(4, min(180, int(round(duration / seconds_per_bar))))
    frames = chroma.shape[1]
    rows, times = [], []
    for i in range(bars):
        a = int(i * frames / bars)
        b = max(a + 1, int((i + 1) * frames / bars))
        rows.append(np.mean(chroma[:, a:b], axis=1))
        times.append((i * duration / bars, min(duration, (i + 1) * duration / bars)))
    return rows, times


def midi_to_note(midi):
    midi = int(round(float(midi)))
    octave = midi // 12 - 1
    return f"{NOTE_NAMES[midi % 12]}{octave}"


def chord_root_midi(chord, octave=2):
    root = str(chord or "C").strip()
    root = root[:2] if len(root) > 1 and root[1] in "#b" else root[:1]
    flat_map = {"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10}
    pc = flat_map.get(root, NOTE_NAMES.index(root) if root in NOTE_NAMES else 0)
    return 12 * (octave + 1) + pc


def fallback_notes_for_chord(chord, instrument):
    root = chord_root_midi(chord, 2 if instrument == "bass5" else 3)
    minor = "m" in str(chord) and "maj" not in str(chord).lower()
    if instrument == "piano":
        return [midi_to_note(root), midi_to_note(root + (3 if minor else 4)), midi_to_note(root + 7)]
    return [midi_to_note(root), midi_to_note(root + 7), midi_to_note(root + 12), midi_to_note(root + 7)]


def transcribe_bar_notes(y_focus, sr, bar_times, chords, instrument):
    if instrument == "piano":
        return [fallback_notes_for_chord(ch, instrument) for ch in chords]

    fmin = float(librosa.note_to_hz("B0" if instrument == "bass5" else "E2"))
    fmax = float(librosa.note_to_hz("G4" if instrument == "bass5" else "E6"))
    try:
        n_fft = 4096
        hop = 1024
        mag = np.abs(librosa.stft(y_focus, n_fft=n_fft, hop_length=hop))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
        frame_times = librosa.frames_to_time(np.arange(mag.shape[1]), sr=sr, hop_length=hop)
        freq_mask = (freqs >= fmin) & (freqs <= fmax)
        use_freqs = freqs[freq_mask]
        use_mag = mag[freq_mask]
        weight = 1.0 / np.sqrt(np.maximum(use_freqs, 30.0))
        use_mag = use_mag * weight[:, None]
    except Exception:
        return [fallback_notes_for_chord(ch, instrument) for ch in chords]

    all_notes = []
    for idx, (start, end) in enumerate(bar_times):
        notes = []
        span = max(0.2, end - start)
        for beat in range(4):
            a = start + span * beat / 4
            b = start + span * (beat + 1) / 4
            frames = (frame_times >= a) & (frame_times < b)
            if not np.any(frames):
                continue
            spectrum = np.mean(use_mag[:, frames], axis=1)
            if spectrum.size == 0 or float(np.max(spectrum)) <= 1e-8:
                continue
            peak = int(np.argmax(spectrum))
            hz = float(use_freqs[peak])
            if hz > 0:
                notes.append(midi_to_note(int(round(float(librosa.hz_to_midi(hz))))))
        if len(notes) < 2:
            notes = fallback_notes_for_chord(chords[idx] if idx < len(chords) else "C", instrument)
        all_notes.append(notes[:4])
    return all_notes


def similarity(a, b):
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(a[i] == b[i] for i in range(n)) / max(len(a), len(b))


def build_structure(chords, notes):
    if not chords:
        return []
    block = 8
    chunks = []
    for i in range(0, len(chords), block):
        chunks.append({"chords": chords[i:i + block], "notes": notes[i:i + block], "start": i})

    clusters, assignments = [], []
    for chunk in chunks:
        best_idx, best_sim = -1, 0.0
        for idx, prototype in enumerate(clusters):
            s = similarity(chunk["chords"], prototype["chords"])
            if s > best_sim:
                best_idx, best_sim = idx, s
        if best_sim >= 0.72:
            assignments.append(best_idx)
        else:
            clusters.append(chunk)
            assignments.append(len(clusters) - 1)

    counts = {i: assignments.count(i) for i in set(assignments)}
    repeated = [i for i, count in counts.items() if count > 1]
    labels = {}
    first_cluster = assignments[0]
    if counts[first_cluster] == 1 and len(chunks) > 1:
        labels[first_cluster] = "INTRO"
    repeated_order = []
    for cluster_id in assignments:
        if cluster_id in repeated and cluster_id not in repeated_order:
            repeated_order.append(cluster_id)
    if repeated_order:
        labels.setdefault(repeated_order[0], "ESTROFE")
    if len(repeated_order) > 1:
        labels.setdefault(repeated_order[1], "REFRÃO")
    remaining_names = ["INTERLÚDIO", "PONTE", "FINAL"]
    for cluster_id in range(len(clusters)):
        if cluster_id not in labels:
            labels[cluster_id] = remaining_names.pop(0) if remaining_names else f"SECÇÃO {cluster_id + 1}"
    last_cluster = assignments[-1]
    if counts[last_cluster] == 1 and len(chunks) > 2:
        labels[last_cluster] = "FINAL"

    sections, emitted = [], set()
    for cluster_id in assignments:
        if cluster_id in emitted:
            continue
        emitted.add(cluster_id)
        cluster = clusters[cluster_id]
        sections.append({
            "name": labels[cluster_id],
            "repeat": counts[cluster_id],
            "chords": cluster["chords"],
            "notes": cluster["notes"],
        })
    return sections


def dominant_notes(chroma):
    energy = np.nan_to_num(np.mean(chroma, axis=1), nan=0.0)
    order = np.argsort(energy)[::-1][:10]
    return [NOTE_NAMES[int(i)] for i in order]


def analyze_audio(path: Path, instrument: str):
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    if duration < 1.0:
        raise ValueError("O áudio é demasiado curto para analisar.")

    stems = separate_sources(y, sr)
    y_focus, focus_label = instrument_focus(stems, instrument)
    y_perc = stems["drums"]
    y_harm = stems["harmonic"]

    tempo, beat_frames = librosa.beat.beat_track(y=y_perc, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    if not np.isfinite(tempo) or tempo <= 0:
        tempo = 120.0
    if tempo < 45:
        tempo *= 2
    elif tempo > 190:
        tempo /= 2

    chord_source = stems["accompaniment"] if instrument == "bass5" else y_harm
    chroma = librosa.feature.chroma_cqt(y=chord_source, sr=sr)
    key_chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr)
    focus_chroma = librosa.feature.chroma_stft(y=y_focus, sr=sr, n_fft=4096, hop_length=512)
    key = estimate_key(key_chroma)

    rows, bar_times = bar_rows_and_times(chroma, beat_frames, sr, duration)
    if len(rows) < 4:
        rows, bar_times = uniform_bar_rows(chroma, duration, tempo)

    score_rows = [chord_scores(row) for row in rows]
    chords = smooth_chords(score_rows)
    if len(bar_times) > len(chords):
        bar_times = bar_times[:len(chords)]
    elif len(bar_times) < len(chords):
        _, bar_times = uniform_bar_rows(chroma, duration, tempo)
        bar_times = bar_times[:len(chords)]

    bar_notes = transcribe_bar_notes(y_focus, sr, bar_times, chords, instrument)
    sections = build_structure(chords, bar_notes)
    notes = dominant_notes(focus_chroma)

    timeline = []
    for i, chord in enumerate(chords):
        start, end = bar_times[i] if i < len(bar_times) else (0.0, 0.0)
        timeline.append({
            "bar": i + 1,
            "start": round(float(start), 2),
            "end": round(float(end), 2),
            "chord": chord,
            "notes": bar_notes[i] if i < len(bar_notes) else [],
        })

    beat_count = len(beat_frames)
    if beat_count >= 32 and duration >= 30 and _rms_energy(y) > 0.002:
        signal = "Boa"
    elif beat_count >= 12:
        signal = "Média"
    else:
        signal = "Limitada"

    return {
        "tempo": round(tempo),
        "key": key,
        "meter": "4/4",
        "duration": round(duration, 1),
        "instrument": instrument,
        "detected_notes": notes,
        "sections": sections,
        "timeline": timeline,
        "analysis_signal": signal,
        "bars_analyzed": len(chords),
        "separation": {
            "mode": "Separação espectral assistida",
            "focus": focus_label,
            "energies": stems["energies"],
        },
        "note": "Transcrição automática assistida. Revê acordes e notas antes da exportação final.",
    }
