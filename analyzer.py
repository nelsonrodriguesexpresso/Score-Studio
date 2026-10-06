from pathlib import Path
import numpy as np
import librosa

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

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
    return 0.026 if suffix in expected.get(rel, set()) else 0.0


def chord_scores(vector, key=None, bass_vector=None):
    """
    Score chord candidates using harmonic chroma plus low-register evidence.

    The older detector sometimes selected attractive-looking but wrong 7th/sus
    chords from melody notes. This version prefers a simple triad unless the
    extra chord tone is genuinely present and uses bass energy to stabilise the
    root without forcing every inversion to root position.
    """
    vector = np.nan_to_num(np.asarray(vector, dtype=float), nan=0.0)
    total = float(np.sum(np.maximum(vector, 0.0)))
    if total <= 1e-10:
        return np.full(len(CHORD_NAMES), -1.0)

    norm = vector / (np.linalg.norm(vector) + 1e-9)
    l1 = np.maximum(vector, 0.0) / (total + 1e-9)
    scores = CHORD_TEMPLATES @ norm

    bass_l1 = None
    if bass_vector is not None:
        bass = np.maximum(np.nan_to_num(np.asarray(bass_vector, dtype=float), nan=0.0), 0.0)
        bass_total = float(np.sum(bass))
        if bass_total > 1e-10:
            bass_l1 = bass / bass_total

    extension_interval = {
        "7": 10,
        "maj7": 11,
        "m7": 10,
        "sus2": 2,
        "sus4": 5,
        "dim": 6,
    }

    for i, (root, suffix, mask, penalty) in enumerate(CHORD_META):
        leakage = float(np.sum(l1[~mask]))
        root_energy = float(l1[root])

        scores[i] += 0.095 * root_energy
        scores[i] -= 0.20 * leakage
        scores[i] -= penalty

        if bass_l1 is not None:
            root_bass = float(bass_l1[root])
            third_pc = (root + (3 if suffix.startswith("m") or suffix == "dim" else 4)) % 12
            fifth_pc = (root + (6 if suffix == "dim" else 7)) % 12
            chord_bass = root_bass + 0.42 * float(bass_l1[third_pc]) + 0.55 * float(bass_l1[fifth_pc])
            scores[i] += 0.19 * root_bass + 0.055 * chord_bass

        if suffix in extension_interval:
            extra_pc = (root + extension_interval[suffix]) % 12
            extra = float(l1[extra_pc])

            if suffix in {"7", "maj7", "m7"}:
                if extra < 0.055:
                    scores[i] -= 0.105
                elif extra < 0.085:
                    scores[i] -= 0.045

            elif suffix in {"sus2", "sus4"}:
                major_third = float(l1[(root + 4) % 12])
                minor_third = float(l1[(root + 3) % 12])
                if max(major_third, minor_third) > extra * 0.95:
                    scores[i] -= 0.075

            elif suffix == "dim" and extra < 0.07:
                scores[i] -= 0.07

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


def low_register_chroma(y_harm, sr, hop_length, target_frames):
    """Fold the lower musical register into 12 pitch classes for root support."""
    try:
        cqt = np.abs(librosa.cqt(
            y=y_harm,
            sr=sr,
            hop_length=hop_length,
            fmin=librosa.note_to_hz("C1"),
            n_bins=48,
            bins_per_octave=12,
        ))
        low = cqt[:30]
        chroma = np.zeros((12, low.shape[1]), dtype=float)
        for bin_index in range(low.shape[0]):
            chroma[bin_index % 12] += low[bin_index]
        chroma /= np.max(chroma, axis=0, keepdims=True) + 1e-9
        return chroma[:, :target_frames]
    except Exception:
        return np.zeros((12, target_frames), dtype=float)


def grouped_bar_rows(chroma, bass_chroma, beat_frames, beat_times, key, beats_per_bar=4):
    """
    Build one observation per bar while preserving beat-level evidence.
    """
    beat_rows = beat_rows_from_chroma(chroma, beat_frames)
    bass_beats = beat_rows_from_chroma(bass_chroma, beat_frames)

    if len(beat_rows) < beats_per_bar * 2:
        return [], [], [], []

    phase = choose_bar_phase(beat_rows, key, beats_per_bar)
    rows, bass_rows, beat_groups, times = [], [], [], []

    usable = min(len(beat_rows), len(bass_beats) if bass_beats else len(beat_rows))

    for i in range(phase, usable - beats_per_bar + 1, beats_per_bar):
        group = np.asarray(beat_rows[i:i + beats_per_bar])
        rows.append(0.74 * np.median(group, axis=0) + 0.26 * np.mean(group, axis=0))

        if bass_beats:
            bgroup = np.asarray(bass_beats[i:i + beats_per_bar])
            bass_rows.append(0.60 * np.median(bgroup, axis=0) + 0.40 * np.mean(bgroup, axis=0))
        else:
            bass_rows.append(np.zeros(12, dtype=float))

        beat_groups.append(list(group))
        if i < len(beat_times):
            times.append(float(beat_times[i]))

    return rows, bass_rows, beat_groups, times


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


def _score_margin(scores):
    if len(scores) < 2:
        return 0.0
    top = np.partition(np.asarray(scores, dtype=float), -2)[-2:]
    return float(top[-1] - top[-2])


def _root_of_chord(name):
    for note in sorted(NOTE_NAMES, key=len, reverse=True):
        if name.startswith(note):
            return note
    return name


def _simple_variant(name):
    root = _root_of_chord(name)
    suffix = name[len(root):]
    if suffix in {"7", "maj7", "sus2", "sus4"}:
        return root
    if suffix == "m7":
        return root + "m"
    return name


def stabilise_chord_sequence(chords, score_rows):
    """
    Remove isolated one-bar mistakes and quality flicker.
    """
    if not chords:
        return chords

    result = list(chords)
    margins = [_score_margin(s) for s in score_rows]

    for i in range(1, len(result) - 1):
        prev_chord, current, next_chord = result[i - 1], result[i], result[i + 1]

        if prev_chord == next_chord and current != prev_chord and margins[i] < 0.105:
            result[i] = prev_chord
            continue

        simple = _simple_variant(current)
        if simple != current:
            same_root_neighbour = (
                _root_of_chord(prev_chord) == _root_of_chord(current)
                or _root_of_chord(next_chord) == _root_of_chord(current)
            )
            if same_root_neighbour and margins[i] < 0.085:
                result[i] = simple

    for i in range(1, len(result) - 1):
        if result[i - 1] == result[i + 1] and result[i] != result[i - 1] and margins[i] < 0.075:
            result[i] = result[i - 1]

    return result


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

    bass_chroma = low_register_chroma(y_harm, sr, hop, frames)
    rows, bass_rows, beat_groups, bar_times = grouped_bar_rows(
        chroma,
        bass_chroma,
        beat_frames,
        beat_times,
        key,
        beats_per_bar=4,
    )

    if len(rows) < 4:
        rows, bar_times = uniform_bar_chroma(chroma, duration, tempo)
        bass_rows = [np.zeros(12, dtype=float) for _ in rows]
        beat_groups = [[] for _ in rows]

    score_rows = []
    for row, bass_row, beat_group in zip(rows, bass_rows, beat_groups):
        bar_scores = chord_scores(row, key=key, bass_vector=bass_row)

        if beat_group:
            beat_scores = [
                chord_scores(beat, key=key, bass_vector=bass_row)
                for beat in beat_group
            ]
            beat_mean = np.mean(np.asarray(beat_scores), axis=0)
            combined = 0.67 * bar_scores + 0.33 * beat_mean
        else:
            combined = bar_scores

        score_rows.append(combined)

    chords = smooth_chords(score_rows, transition_penalty=0.115)
    chords = stabilise_chord_sequence(chords, score_rows)

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
        "analysis_mode": "precision_plus_bass_consensus",
        "note": "Precisão+ usa consenso por batida, registo grave para estabilizar a fundamental, preferência por tríades quando extensões são ambíguas e remoção de acordes isolados.",
    }
