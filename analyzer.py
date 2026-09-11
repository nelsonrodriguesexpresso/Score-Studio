from pathlib import Path
import math
import numpy as np
import librosa

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def estimate_key(chroma):
    vector = np.mean(chroma, axis=1)
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


def bar_chroma_from_beats(chroma, beat_frames):
    if len(beat_frames) < 8:
        return []
    rows = []
    for i in range(0, len(beat_frames) - 4, 4):
        start = int(beat_frames[i])
        end = int(beat_frames[min(i + 4, len(beat_frames) - 1)])
        if end <= start:
            continue
        rows.append(np.mean(chroma[:, start:end], axis=1))
    return rows


def uniform_bar_chroma(chroma, duration, tempo):
    seconds_per_bar = 240.0 / max(tempo, 1.0)
    bars = max(4, min(160, int(round(duration / seconds_per_bar))))
    frames = chroma.shape[1]
    rows = []
    for i in range(bars):
        a = int(i * frames / bars)
        b = max(a + 1, int((i + 1) * frames / bars))
        rows.append(np.mean(chroma[:, a:b], axis=1))
    return rows


def similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


def build_structure(chords):
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
    for cluster_id in assignments:
        if cluster_id in emitted:
            continue
        emitted.add(cluster_id)
        sections.append({
            "name": labels[cluster_id],
            "repeat": counts[cluster_id],
            "chords": clusters[cluster_id],
        })
    return sections


def dominant_notes(y_harm, sr, instrument, chroma):
    energy = np.mean(chroma, axis=1)
    if not np.any(np.isfinite(energy)):
        return []
    order = np.argsort(np.nan_to_num(energy, nan=0.0))[::-1][:10]
    return [NOTE_NAMES[int(i)] for i in order]


def analyze_audio(path: Path, instrument: str):
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    if duration < 1.0:
        raise ValueError("O áudio é demasiado curto para analisar.")
    y_harm, y_perc = librosa.effects.hpss(y)
    tempo, beat_frames = librosa.beat.beat_track(y=y_perc, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    if not np.isfinite(tempo) or tempo <= 0:
        tempo = 120.0
    if tempo < 45:
        tempo *= 2
    elif tempo > 190:
        tempo /= 2
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr)
    key_chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key = estimate_key(key_chroma)
    rows = bar_chroma_from_beats(chroma, beat_frames)
    if len(rows) < 4:
        rows = uniform_bar_chroma(chroma, duration, tempo)
    score_rows = [chord_scores(row) for row in rows]
    chords = smooth_chords(score_rows)
    sections = build_structure(chords)
    notes = dominant_notes(y_harm, sr, instrument, chroma)
    beat_count = len(beat_frames)
    if beat_count >= 32 and duration >= 30:
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
        "analysis_signal": signal,
        "bars_analyzed": len(chords),
        "note": "Análise automática assistida. Revê acordes, estrutura e notas antes da exportação final.",
    }
