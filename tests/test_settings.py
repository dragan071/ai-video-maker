import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from settings import SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def test_round_trip_preserves_api_key_and_options(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            expected = SettingsStore.defaults()
            expected.update(
                {
                    "provider": "google",
                    "mode": "image",
                    "api_key": "secret-key",
                    "google_api_key": "google-secret",
                    "model": "grok-imagine-video-1.5-lite",
                    "duration": 12,
                    "aspect_ratio": "9:16",
                    "resolution": "1080p",
                    "generate_audio": False,
                    "google_duration": 14,
                    "google_aspect_ratio": "9:16",
                    "google_resolution": "4k",
                    "image_path": str(Path(directory) / "start.png"),
                    "output_dir": str(Path(directory) / "videos"),
                }
            )

            store.save(expected)

            self.assertEqual(store.load(), expected)
            self.assertNotIn("secret-key", repr(store))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_load_ignores_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "provider": "unknown",
                        "mode": "unknown",
                        "api_key": 123,
                        "google_api_key": 456,
                        "model": "unknown",
                        "duration": 99,
                        "aspect_ratio": "invalid",
                        "resolution": "8K",
                        "generate_audio": "yes",
                        "google_model": "veo-old",
                        "google_duration": 2,
                        "google_aspect_ratio": "1:1",
                        "google_resolution": "8K",
                    }
                ),
                encoding="utf-8",
            )

            loaded = SettingsStore(path).load()

            self.assertEqual(loaded["provider"], "grok")
            self.assertEqual(loaded["mode"], "text")
            self.assertEqual(loaded["api_key"], "")
            self.assertEqual(loaded["google_api_key"], "")
            self.assertEqual(loaded["model"], "grok-imagine-video-1.5")
            self.assertEqual(loaded["duration"], 8)
            self.assertEqual(loaded["aspect_ratio"], "16:9")
            self.assertEqual(loaded["resolution"], "480p")
            self.assertTrue(loaded["generate_audio"])
            self.assertEqual(loaded["google_model"], "gemini-omni-1.2-flash")
            self.assertEqual(loaded["google_duration"], 10)
            self.assertEqual(loaded["google_aspect_ratio"], "16:9")
            self.assertEqual(loaded["google_resolution"], "720p")

    def test_legacy_grok_settings_remain_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "api_key": "existing-xai-key",
                        "model": "grok-imagine-video",
                        "duration": 7,
                        "aspect_ratio": "1:1",
                        "resolution": "720p",
                        "generate_audio": False,
                        "output_dir": str(Path(directory) / "old-videos"),
                    }
                ),
                encoding="utf-8",
            )

            loaded = SettingsStore(path).load()

            self.assertEqual(loaded["provider"], "grok")
            self.assertEqual(loaded["mode"], "text")
            self.assertEqual(loaded["api_key"], "existing-xai-key")
            self.assertEqual(loaded["model"], "grok-imagine-video")
            self.assertEqual(loaded["duration"], 7)
            self.assertEqual(loaded["google_model"], "gemini-omni-1.2-flash")


if __name__ == "__main__":
    unittest.main()
