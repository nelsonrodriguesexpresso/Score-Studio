from pathlib import Path
import json
import sys

from faster_whisper import WhisperModel


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Falta o ficheiro de áudio.")

    audio_path = Path(sys.argv[1])
    model = WhisperModel(
        "/app/models/whisper-base",
        device="cpu",
        compute_type="int8",
        cpu_threads=1,
        num_workers=1,
    )
    segments, info = model.transcribe(
        str(audio_path),
        language="pt",
        task="transcribe",
        initial_prompt="Letra de uma canção em português de Portugal.",
        beam_size=3,
        best_of=3,
        vad_filter=True,
        condition_on_previous_text=False,
        repetition_penalty=1.1,
        no_repeat_ngram_size=3,
    )
    items = []
    for segment in segments:
        text = (segment.text or "").strip()
        if text:
            items.append({
                "start": round(float(segment.start), 2),
                "end": round(float(segment.end), 2),
                "text": text,
            })
    print(json.dumps({
        "text": "\n".join(item["text"] for item in items),
        "segments": items,
        "language": "pt-PT",
        "language_probability": round(float(getattr(info, "language_probability", 0) or 0), 3),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
