import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
import numpy as np

from audio_guides import RATE, generate_guide, prepare, render_wav
from analyzer import build_structure


class GuideTests(unittest.TestCase):
    def payload(self, **changes):
        return dict(dict(kind="click", duration=12, tempo=120, meter="4/4", mode="fixed",
                         cue_sections=[{"name": "INTRO", "start": 0}, {"name": "Refrão", "start": 8}],
                         lead_beats=4), **changes)

    def read(self, path):
        with wave.open(str(path), "rb") as f:
            self.assertEqual((f.getnchannels(), f.getsampwidth(), f.getframerate()), (1, 2, RATE))
            return np.frombuffer(f.readframes(f.getnframes()), dtype="<i2")

    def test_repeated_sections_keep_chronological_order(self):
        chords = ["C"] * 8 + ["G"] * 8 + ["C"] * 8 + ["G"] * 8
        grouped = build_structure(chords)
        chronological = build_structure(chords, chronological=True)
        self.assertEqual(len(grouped), 2)
        self.assertEqual([s["start_bar"] for s in chronological], [0, 8, 16, 24])
        self.assertEqual([s["name"] for s in chronological], ["ESTROFE", "REFRÃO", "ESTROFE", "REFRÃO"])

    def test_detected_beats_preserve_variations_and_offset_accent(self):
        _, clicks = prepare(self.payload(mode="detected", beat_times=[.1, .6, 1.12, 1.67, 2.23], offset=-.2))
        self.assertAlmostEqual(clicks[0][0], .4)
        self.assertFalse(clicks[0][1])
        self.assertTrue(clicks[-1][1])
        self.assertAlmostEqual(clicks[-1][0], 2.03)

    def test_click_exact_duration_silence_and_accent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "click.wav"
            generate_guide(self.payload(duration=2.25, offset=.1), path)
            sound = self.read(path)
        self.assertEqual(len(sound), round(2.25 * RATE))
        self.assertFalse(sound[:round(.1 * RATE)].any())
        self.assertGreater(np.max(np.abs(sound[2205:3205])), np.max(np.abs(sound[13230:14230])))

    def test_voice_anticipation_zero_origin_and_duration(self):
        sample = np.ones(RATE // 2, dtype=np.float32) * .3
        with tempfile.TemporaryDirectory() as folder, patch("audio_guides.speech", return_value=sample):
            path = Path(folder) / "voice.wav"
            generate_guide(self.payload(kind="cues"), path)
            sound = self.read(path)
        self.assertEqual(len(sound), 12 * RATE)
        self.assertTrue(sound[:RATE//2].all())
        self.assertFalse(sound[RATE:6*RATE].any())
        self.assertTrue(sound[6*RATE:6*RATE+RATE//2].all())

    def test_block_boundary_does_not_cut_sound(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "boundary.wav"
            render_wav(path, 2, [(RATE-10, np.ones(30, dtype=np.float32)*.2)])
            sound = self.read(path)
        self.assertEqual(np.count_nonzero(sound), 30)

    def test_meter_accent(self):
        for meter, count in [("3/4", 3), ("6/8", 6), ("2/4", 2)]:
            _, clicks = prepare(self.payload(meter=meter))
            self.assertEqual([i for i, (_, accent) in enumerate(clicks) if accent][:2], [0, count])

    def test_invalid_and_excessive_input(self):
        for changes in [dict(duration=float("nan")), dict(duration=1801), dict(tempo=0),
                        dict(mode="detected", beat_times=[1, .5]), dict(offset=11), dict(accent=.5)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                prepare(self.payload(**changes))

    def test_voice_overlap_is_rejected(self):
        sample = np.ones(RATE, dtype=np.float32) * .3
        with tempfile.TemporaryDirectory() as folder, patch("audio_guides.speech", return_value=sample):
            with self.assertRaisesRegex(ValueError, "sobrepostos"):
                generate_guide(self.payload(kind="cues", cue_sections=[{"name":"Intro", "start":0}, {"name":"Solo", "start":.5}]), Path(folder)/"v.wav")


if __name__ == "__main__":
    unittest.main()
