"""Protect channel isolation: implicit ffmpeg layouts can silently remix quad."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
import soundfile as sf
from playback_mix import source_cache, generate_mix


class MixerTests(unittest.TestCase):
    def test_quad_keeps_music_stereo_and_guides_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            rate = 44100
            t = np.arange(8 * rate) / rate
            music = np.stack([.1 * np.sin(2*np.pi*330*t), .1 * np.sin(2*np.pi*660*t)], axis=1)
            sf.write(tmp / 'source.wav', music, rate, subtype='PCM_16')
            token = source_cache.save(tmp / 'source.wav', 8)
            payload = dict(playback_token=token, duration=8, tempo=120, meter='4/4', mode='fixed',
                           cue_sections=[dict(name='Introdução', start=0)], lead_beats=0)
            generate_mix(payload, tmp / 'quad.wav', multichannel=True)
            data, actual_rate = sf.read(tmp / 'quad.wav')
            self.assertEqual(actual_rate, rate)
            self.assertEqual(data.shape, (8 * rate, 4))
            self.assertLess(np.max(abs(data[:, :2] - music)), .00004)
            self.assertGreater(np.max(abs(data[:, 2])), .1)
            self.assertGreater(np.max(abs(data[:, 3])), .1)
            self.assertFalse(np.array_equal(data[:, 2], data[:, 3]))


if __name__ == '__main__':
    unittest.main()
