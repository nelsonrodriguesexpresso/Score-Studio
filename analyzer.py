from pathlib import Path
import numpy as np
import librosa

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])\n\n# Optional deep-learning chord engine. It is installed only on the local Score Studio\n# workstation; cloud/fallback deployments continue to use the spectral analyser.\n_LV_CHORDIA_ENSEMBLE = None\n_LV_CHORDIA_ERROR = None

CHORD_QUALITIES = {
    "": ([0, 4, 7], [1.00, 0.92, 0.82], 0.000),
    "m": ([0, 3, 7], [1.00, 0.92, 0.82], 0.000),
    "7": ([0, 4, 7, 10], [1.00, 0.90, 0.80, 0.60], 0.045),
    "maj7": ([0, 4, 7, 11], [1.00, 0.90, 0.80, 0.58], 0.055),
    "m7": ([0, 3, 7, 10], [1.00, 0.90, 0.80, 0.58], 0.050),
    "sus2": ([0, 2, 7], [1.00, 0.82, 0.82], 0.040),
    "sus4": ([0, 5, 7], [1.00, 0.84, 0.82], 0.040),
    "dim": ([0, 3, 6], [1.00, 0.86, 0.80], 0.055),
}


def estimate_key(chroma):
    vector = np.nan_to_num(np.mean(chroma, axis=1), nan=0.0)
    vector /= np.linalg.norm(vector) + 1e-9
    best = (-999.0, "C")
    for root in range(12):
        for profile, suffix in ((MAJOR_PROFILE, ""), (MINOR_PROFILE, "m")):
            p = np.roll(profile, root).astype(float)
            p /= np.linalg.norm(p) + 1e-9
            score = float(vector @ p)
            if score > best[0]:
                best = (score, NOTE_NAMES[root] + suffix)
    return best[1]


def build_chord_templates():
    templates = []
    names = []
    metadata = []
    for root in range(12):
        for suffix, (intervals, weights, penalty) in CHORD_QUALITIES.items():
            v = np.zeros(12, dtype=float)
            mask = np.zeros(12, dtype=bool)
            for interval, weight in zip(intervals, weights):
                pc = (root + interval) % 12
                v[pc] = weight
                mask[pc] = True
            v /= np.linalg.norm(v) + 1e-9
            templates.append(v)
            names.append(NOTE_NAMES[root] + suffix)
            metadata.append((root, suffix, mask, penalty))
    return np.asarray(templates), names, metadata


CHORD_TEMPLATES, CHORD_NAMES, CHORD_META = build_chord_templates()


def parse_key(key):
    minor = key.endswith("m")
    name = key[:-1] if minor else key
    try:
        return NOTE_NAMES.index(name), minor
    except ValueError:
        return 0, False


def diatonic_bonus(root, suffix, key):
    key_root, minor = parse_key(key)
    rel = (root - key_root) % 12
    if minor:
        expected = {
            0: {"m", "m7"},
            2: {"dim"},
            3: {"", "maj7"},
            5: {"m", "m7"},
            7: {"m", "", "7"},
            8: {"", "maj7"},
            10: {"", "7"},
        }
    else:
        expected = {
            0: {"", "maj7"},
            2: {"m", "m7"},
            4: {"m", "m7"},
            5: {"", "maj7"},
            7: {"", "7", "sus4"},
            9: {"m", "m7"},
            11: {"dim"},
        }
    return 0.045 if suffix in expected.get(rel, set()) else 0.0


def chord_scores(vector, key=None):
    vector = np.nan_to_num(np.asarray(vector, dtype=float), nan=0.0)
    total = float(np.sum(np.maximum(vector, 0.0)))
    if total <= 1e-10:
        return np.full(len(CHORD_NAMES), -1.0)

    norm = vector / (np.linalg.norm(vector) + 1e-9)
    l1 = np.maximum(vector, 0.0) / (total + 1e-9)
    scores = CHORD_TEMPLATES @ norm

    for i, (root, suffix, mask, penalty) in enumerate(CHORD_META):
        leakage = float(np.sum(l1[~mask]))
        root_energy = float(l1[root])
        scores[i] += 0.10 * root_energy
        scores[i] -= 0.18 * leakage
        scores[i] -= penalty
        if key:
            scores[i] += diatonic_bonus(root, suffix, key)
    return scores


def smooth_chords(score_rows, transition_penalty=0.085):
    if not score_rows:
        return []
    obs = np.asarray(score_rows, dtype=float)
    n_time, n_chords = obs.shape
    dp = np.full((n_time, n_chords), -1e9, dtype=float)
    back = np.zeros((n_time, n_chords), dtype=int)
    dp[0] = obs[0]

    roots = np.array([meta[0] for meta in CHORD_META])
    for t in range(1, n_time):
        for c in range(n_chords):
            transition = np.full(n_chords, transition_penalty, dtype=float)
            transition[c] = 0.0
            transition[roots == roots[c]] *= 0.45
            candidates = dp[t - 1] - transition
            prev = int(np.argmax(candidates))
            dp[t, c] = obs[t, c] + candidates[prev]
            back[t, c] = prev

    idx = int(np.argmax(dp[-1]))
    path = [idx]
    for t in range(n_time - 1, 0, -1):
        idx = int(back[t, idx])
        path.append(idx)
    path.reverse()
    return [CHORD_NAMES[i] for i in path]


def beat_rows_from_chroma(chroma, beat_frames):
    rows = []
    frames = chroma.shape[1]
    beats = [int(x) for x in beat_frames if 0 <= int(x) < frames]
    if len(beats) < 2:
        return rows

    for i in range(len(beats) - 1):
        a, b = beats[i], beats[i + 1]
        if b <= a:
            continue
        rows.append(np.median(chroma[:, a:b], axis=1))
    return rows


def choose_bar_phase(beat_rows, key, beats_per_bar=4):
    if len(beat_rows) < beats_per_bar * 2:
        return 0
    best_phase, best_score = 0, -1e9
    for phase in range(beats_per_bar):
        margins = []
        for i in range(phase, len(beat_rows) - beats_per_bar + 1, beats_per_bar):
            bar = np.median(np.asarray(beat_rows[i:i + beats_per_bar]), axis=0)
            scores = chord_scores(bar, key)
            if len(scores) >= 2:
                top = np.partition(scores, -2)[-2:]
                margins.append(float(top[-1] - top[-2]))
        if margins:
            score = float(np.median(margins))
            if score > best_score:
                best_phase, best_score = phase, score
    return best_phase


def bars_from_beats(chroma, beat_frames, beat_times, key, beats_per_bar=4):
    beat_rows = beat_rows_from_chroma(chroma, beat_frames)
    if len(beat_rows) < beats_per_bar * 2:
        return [], []

    phase = choose_bar_phase(beat_rows, key, beats_per_bar)
    rows = []
    times = []

    for i in range(phase, len(beat_rows) - beats_per_bar + 1, beats_per_bar):
        group = np.asarray(beat_rows[i:i + beats_per_bar])
        median_row = np.median(group, axis=0)
        mean_row = np.mean(group, axis=0)
        rows.append(0.72 * median_row + 0.28 * mean_row)
        if i < len(beat_times):
            times.append(float(beat_times[i]))

    return rows, times


def uniform_bar_chroma(chroma, duration, tempo):
    seconds_per_bar = 240.0 / max(tempo, 1.0)
    bars = max(4, min(240, int(round(duration / seconds_per_bar))))
    frames = chroma.shape[1]
    rows = []
    for i in range(bars):
        a = int(i * frames / bars)
        b = max(a + 1, int((i + 1) * frames / bars))
        rows.append(np.median(chroma[:, a:b], axis=1))
    times = [i * duration / bars for i in range(bars)]
    return rows, times


def similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


def build_structure(chords, chronological=False):
    if not chords:
        return []
    block = 8
    chunks = [chords[i:i + block] for i in range(0, len(chords), block)]
    clusters = []
    assignments = []
    for chunk in chunks:
        best_idx, best_sim = -1, 0.0
        for idx, prototype in enumerate(clusters):
            s = similarity(chunk, prototype)
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

    sections = []
    emitted = set()
    for occurrence, cluster_id in enumerate(assignments):
        if cluster_id in emitted and not chronological:
            continue
        emitted.add(cluster_id)
        sections.append({
            "name": labels[cluster_id],
            "repeat": 1 if chronological else counts[cluster_id],
            "chords": clusters[cluster_id],
            **({"start_bar": occurrence * block} if chronological else {}),
        })
    return sections


def dominant_notes(chroma):
    energy = np.mean(chroma, axis=1)
    if not np.any(np.isfinite(energy)):
        return []
    order = np.argsort(np.nan_to_num(energy, nan=0.0))[::-1][:10]
    return [NOTE_NAMES[int(i)] for i in order]


def chord_confidence(score_rows):
    if not score_rows:
        return 0.0
    margins = []
    for scores in score_rows:
        if len(scores) < 2:
            continue
        best = np.partition(np.asarray(scores), -2)[-2:]
        margins.append(float(best[-1] - best[-2]))
    return float(np.median(margins)) if margins else 0.0



def _normalise_lv_chord(label):
    """Convert JAMS-style labels from lv-chordia into compact musician-friendly names."""
    if not label or label == "N":
        return "N"

    # Preserve inversions while simplifying the main chord quality.
    bass = ""
    core = str(label)
    if "/" in core:
        core, bass = core.split("/", 1)
        bass = "/" + bass.split(":", 1)[0]

    if ":" not in core:
        return core + bass

    root, quality = core.split(":", 1)
    quality = quality.strip()
    replacements = {
        "maj": "",
        "min": "m",
        "maj7": "maj7",
        "min7": "m7",
        "7": "7",
        "dim": "dim",
        "dim7": "dim7",
        "hdim7": "m7b5",
        "aug": "aug",
        "sus2": "sus2",
        "sus4": "sus4",
        "maj6": "6",
        "min6": "m6",
        "9": "9",
        "maj9": "maj9",
        "min9": "m9",
        "11": "11",
        "13": "13",
    }
    compact = replacements.get(quality)
    if compact is None:
        # lv-chordia can emit large-vocabulary labels. Keep useful labels, but
        # avoid exposing JAMS punctuation that is awkward in the editor.
        compact = quality.replace("(", "").replace(")", "").replace(",", "")
        compact = compact.replace("min", "m").replace("maj", "maj")
    return f"{root}{compact}{bass}"


def _load_lv_chordia_ensemble():
    """Load the five-model chord ensemble once and keep it resident for later songs."""
    global _LV_CHORDIA_ENSEMBLE, _LV_CHORDIA_ERROR
    if _LV_CHORDIA_ENSEMBLE is not None:
        return _LV_CHORDIA_ENSEMBLE
    if _LV_CHORDIA_ERROR is not None:
        return None

    try:
        from lv_chordia.chord_recognition import load_ensemble
        _LV_CHORDIA_ENSEMBLE = load_ensemble(use_gpu=False)
        return _LV_CHORDIA_ENSEMBLE
    except Exception as exc:
        _LV_CHORDIA_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def deep_chord_segments(path: Path):
    """Return time-aligned chords from a trained deep-learning ensemble when available."""
    ensemble = _load_lv_chordia_ensemble()
    if ensemble is None:
        return None

    try:
        from lv_chordia.chord_recognition import recognize_with_ensemble
        raw = recognize_with_ensemble(
            ensemble,
            str(path),
            chord_dict_name="submission",
        )
    except Exception:
        return None

    segments = []
    for item in raw or []:
        try:
            start = max(0.0, float(item.get("start_time", 0.0)))
            end = max(start, float(item.get("end_time", start)))
            chord = _normalise_lv_chord(item.get("chord", "N"))
        except Exception:
            continue
        if end > start:
            segments.append({"start": start, "end": end, "chord": chord})
    return segments


def chords_from_segments(segments, bar_times, duration, fallback):
    """Collapse time-aligned ML chords into one musically dominant chord per bar."""
    if not segments or not bar_times:
        return fallback

    result = []
    for i, start in enumerate(bar_times):
        end = bar_times[i + 1] if i + 1 < len(bar_times) else duration
        if end <= start:
            result.append(fallback[i] if i < len(fallback) else "N")
            continue

        overlap = {}
        for segment in segments:
            a = max(float(start), float(segment["start"]))
            b = min(float(end), float(segment["end"]))
            if b <= a:
                continue
            chord = segment["chord"]
            overlap[chord] = overlap.get(chord, 0.0) + (b - a)

        # Ignore 'N' if there is a meaningful harmonic candidate in the bar.
        musical = {k: v for k, v in overlap.items() if k != "N"}
        pool = musical or overlap
        if pool:
            result.append(max(pool, key=pool.get))
        else:
            result.append(fallback[i] if i < len(fallback) else "N")

    return result


def analyze_audio(path: Path, instrument: str):
    sr_target = 16000
    hop = 512
    y, sr = librosa.load(str(path), sr=sr_target, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    if duration < 1.0:
        raise ValueError("O áudio é demasiado curto para analisar.")

    y_harm = librosa.effects.harmonic(y, margin=2.0)

    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, n_fft=1024)
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset,
        sr=sr,
        hop_length=hop,
        trim=False,
    )
    tempo = float(np.atleast_1d(tempo)[0])
    if not np.isfinite(tempo) or tempo <= 0:
        tempo = 120.0
    if tempo < 45:
        tempo *= 2
    elif tempo > 190:
        tempo /= 2

    try:
        tuning = float(librosa.estimate_tuning(y=y_harm, sr=sr))
    except Exception:
        tuning = 0.0

    chroma_cqt = librosa.feature.chroma_cqt(
        y=y_harm,
        sr=sr,
        hop_length=hop,
        bins_per_octave=36,
        n_chroma=12,
        tuning=tuning,
        norm=2,
    )
    chroma_cens = librosa.feature.chroma_cens(
        y=y_harm,
        sr=sr,
        hop_length=hop,
        n_chroma=12,
        bins_per_octave=36,
        tuning=tuning,
        norm=2,
    )
    frames = min(chroma_cqt.shape[1], chroma_cens.shape[1])
    chroma = 0.72 * chroma_cqt[:, :frames] + 0.28 * chroma_cens[:, :frames]
    chroma = np.nan_to_num(chroma, nan=0.0)

    key = estimate_key(chroma)
    beat_frames = np.asarray(beat_frames, dtype=int)
    beat_frames = beat_frames[beat_frames < frames]
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop).tolist()

    rows, bar_times = bars_from_beats(chroma, beat_frames, beat_times, key, beats_per_bar=4)
    if len(rows) < 4:
        rows, bar_times = uniform_bar_chroma(chroma, duration, tempo)

    score_rows = [chord_scores(row, key=key) for row in rows]
    spectral_chords = smooth_chords(score_rows, transition_penalty=0.085)

    # Primary chord engine: a trained five-network ensemble (lv-chordia).
    # The spectral detector remains as a fallback and fills gaps/silence.
    ml_segments = deep_chord_segments(path)
    if ml_segments:
        chords = chords_from_segments(
            ml_segments,
            bar_times,
            duration,
            spectral_chords,
        )
        chord_engine = "IA profunda · ensemble LV-Chordia"
    else:
        chords = spectral_chords
        chord_engine = "Análise harmónica local (fallback)"

    sections = build_structure(chords)
    chronological = build_structure(chords, chronological=True)
    cue_sections = []
    for section in chronological:
        index = int(section.get("start_bar", 0))
        if 0 <= index < len(bar_times):
            cue_sections.append({
                "name": section["name"],
                "start": round(float(bar_times[index]), 4),
            })

    notes = dominant_notes(chroma)
    confidence = chord_confidence(score_rows)
    beat_count = len(beat_frames)

    if beat_count >= 24 and confidence >= 0.055:
        signal = "Boa"
    elif beat_count >= 10 and confidence >= 0.025:
        signal = "Média"
    else:
        signal = "Limitada"

    return {
        "tempo": round(tempo),
        "key": key,
        "meter": "4/4",
        "duration": round(duration, 1),
        "audio_duration": duration,
        "beat_times": [round(t, 4) for t in beat_times if t < duration],
        "cue_sections": cue_sections,
        "instrument": instrument,
        "detected_notes": notes,
        "sections": sections,
        "analysis_signal": signal,
        "bars_analyzed": len(chords),
        "chord_confidence": round(confidence, 4),
        "analysis_mode": "deep_chord_ai" if ml_segments else "high_precision_harmonic",
        "chord_engine": chord_engine,
        "deep_chord_segments": len(ml_segments or []),
        "note": (
            "Acordes reconhecidos por um ensemble de redes neurais e alinhados ao compasso. "
            "Casos ambíguos continuam editáveis."
            if ml_segments
            else
            "Motor de IA de acordes indisponível; foi usada a análise harmónica local de alta precisão."
        ),
    }
