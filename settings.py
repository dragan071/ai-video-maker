"""Persistent local settings for the Grok and Google video app."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google_api import GOOGLE_ASPECT_RATIOS, GOOGLE_VIDEO_MODELS
from grok_api import ASPECT_RATIOS, VIDEO_MODELS


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "grok_video_settings.json"


class SettingsError(Exception):
    """A local settings error that can be shown in the interface."""


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = Path(path)

    @staticmethod
    def defaults() -> dict:
        return {
            "provider": "grok",
            "mode": "text",
            "api_key": "",
            "google_api_key": "",
            "model": "grok-imagine-video-1.5",
            "duration": 8,
            "aspect_ratio": "16:9",
            "resolution": "480p",
            "generate_audio": True,
            "google_model": "gemini-omni-1.2-flash",
            "google_duration": 10,
            "google_aspect_ratio": "16:9",
            "google_resolution": "720p",
            "image_path": "",
            "output_dir": str(APP_DIR / "videos"),
        }

    def load(self) -> dict:
        settings = self.defaults()
        if not self.path.exists():
            return settings

        try:
            with self.path.open("r", encoding="utf-8") as source:
                saved = json.load(source)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SettingsError(f"Could not read settings: {exc}") from exc

        if not isinstance(saved, dict):
            raise SettingsError("The settings file is not a valid JSON object.")

        if saved.get("provider") in ("grok", "google"):
            settings["provider"] = saved["provider"]
        if saved.get("mode") in ("text", "image"):
            settings["mode"] = saved["mode"]

        for key in ("api_key", "google_api_key", "image_path"):
            if isinstance(saved.get(key), str):
                settings[key] = saved[key]

        model = saved.get("model")
        if model in VIDEO_MODELS:
            settings["model"] = model
        if self._integer_in_range(saved.get("duration"), 1, 15):
            settings["duration"] = saved["duration"]
        if saved.get("aspect_ratio") in ASPECT_RATIOS:
            settings["aspect_ratio"] = saved["aspect_ratio"]
        resolution = saved.get("resolution")
        if resolution in VIDEO_MODELS[settings["model"]]["resolutions"]:
            settings["resolution"] = resolution
        if isinstance(saved.get("generate_audio"), bool):
            settings["generate_audio"] = saved["generate_audio"]

        google_model = saved.get("google_model")
        if google_model in GOOGLE_VIDEO_MODELS:
            settings["google_model"] = google_model
        if self._integer_in_range(saved.get("google_duration"), 3, 15):
            settings["google_duration"] = saved["google_duration"]
        if saved.get("google_aspect_ratio") in GOOGLE_ASPECT_RATIOS:
            settings["google_aspect_ratio"] = saved["google_aspect_ratio"]
        google_resolution = saved.get("google_resolution")
        if google_resolution in GOOGLE_VIDEO_MODELS[settings["google_model"]]["resolutions"]:
            settings["google_resolution"] = google_resolution

        if isinstance(saved.get("output_dir"), str) and saved["output_dir"].strip():
            settings["output_dir"] = saved["output_dir"]

        return settings

    @staticmethod
    def _integer_in_range(value: object, minimum: int, maximum: int) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum

    def save(self, settings: dict) -> None:
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as destination:
                json.dump(settings, destination, ensure_ascii=False, indent=2)
                destination.write("\n")
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise SettingsError(f"Could not save settings: {exc}") from exc
