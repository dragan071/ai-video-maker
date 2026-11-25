"""Client for Google Gemini Omni Flash video generation."""

from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

from image_input import encode_image


API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
USER_AGENT = "AIVideoMaker/2.0"

GOOGLE_VIDEO_MODELS = {
    "gemini-omni-1.2-flash": {
        "label": "Gemini Omni 1.2 Flash",
        "resolutions": ("360p", "720p", "1080p", "4k"),
    },
}
GOOGLE_ASPECT_RATIOS = ("16:9", "9:16")


class GoogleAPIError(Exception):
    """A Google API or response error suitable for the user interface."""


class GoogleVideoClient:
    def __init__(self, api_key: str, request_timeout: int = 20 * 60) -> None:
        self.api_key = api_key.strip()
        self.request_timeout = request_timeout

    def generate_video(
        self,
        *,
        prompt: str,
        model: str,
        duration: int,
        aspect_ratio: str,
        resolution: str,
        image_path: Path | None = None,
    ) -> tuple[str, bytes]:
        if not self.api_key:
            raise GoogleAPIError("Enter your Google Gemini API key.")
        if not prompt.strip():
            raise GoogleAPIError("The prompt must not be empty.")
        if model not in GOOGLE_VIDEO_MODELS:
            raise GoogleAPIError("The selected Google model is not supported.")
        if not 3 <= duration <= 15:
            raise GoogleAPIError("Google videos can be between 3 and 15 seconds long.")
        if aspect_ratio not in GOOGLE_ASPECT_RATIOS:
            raise GoogleAPIError("Google only supports 16:9 and 9:16 aspect ratios.")
        if resolution not in GOOGLE_VIDEO_MODELS[model]["resolutions"]:
            raise GoogleAPIError("The selected resolution is not supported for the Google model.")

        prompt_input: str | list[dict]
        if image_path is None:
            prompt_input = prompt.strip()
        else:
            image_data, mime_type = encode_image(image_path)
            prompt_input = [
                {"type": "image", "data": image_data, "mime_type": mime_type},
                {"type": "text", "text": prompt.strip()},
            ]

        payload = {
            "model": model,
            "input": prompt_input,
            "response_format": {
                "type": "video",
                "duration": f"{duration}s",
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
            },
            "store": False,
        }
        data = self._request_json(payload)
        status = data.get("status")
        if status not in (None, "completed"):
            detail = self._error_detail(data.get("error"))
            message = f"Google generation did not finish (status: {status or 'unknown'})"
            if detail:
                message += f": {detail}"
            raise GoogleAPIError(message)

        encoded_video = self._find_video_data(data.get("steps"))
        if encoded_video is None:
            raise GoogleAPIError("Google responded without an MP4 video. Please try again.")
        try:
            video_bytes = base64.b64decode(encoded_video)
        except (ValueError, TypeError) as exc:
            raise GoogleAPIError("Google returned an invalid Base64 video.") from exc
        if not video_bytes:
            raise GoogleAPIError("Google returned an empty video.")

        interaction_id = data.get("id")
        if not isinstance(interaction_id, str) or not interaction_id.strip():
            interaction_id = "google-video"
        return interaction_id.strip(), video_bytes

    @staticmethod
    def save_video(video_bytes: bytes, target: Path) -> Path:
        target = Path(target)
        partial = target.with_name(target.name + ".part")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with partial.open("wb") as destination:
                destination.write(video_bytes)
            partial.replace(target)
            return target
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise GoogleAPIError(
                f"Could not save the Google video to disk: {exc}"
            ) from exc

    @staticmethod
    def _find_video_data(steps: object) -> str | None:
        if not isinstance(steps, list):
            return None
        for step in steps:
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            content = step.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "video":
                    continue
                data = part.get("data")
                if isinstance(data, str) and data.strip():
                    return data.strip()
        return None

    def _request_json(self, payload: dict) -> dict:
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = self._error_detail_from_response(raw)
            message = f"Google API error (HTTP {exc.code})"
            if detail:
                message += f": {detail}"
            if exc.code in (401, 403):
                message += ". Check your Google API key, model access and billing"
            elif exc.code == 429:
                message += ". Quota exceeded or insufficient credit; check Google AI Studio"
            if detail or exc.code in (401, 403, 429):
                message += "."
            raise GoogleAPIError(message) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise GoogleAPIError(f"Could not connect to the Google API: {exc}") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GoogleAPIError("The Google API returned an unreadable response.") from None
        if not isinstance(data, dict):
            raise GoogleAPIError("The Google API returned an unexpected response.")
        return data

    @staticmethod
    def _error_detail_from_response(raw: bytes) -> str:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return raw.decode("utf-8", errors="replace").strip()[:500]
        if isinstance(data, dict):
            return GoogleVideoClient._error_detail(data.get("error", data.get("message")))
        return ""

    @staticmethod
    def _error_detail(error: object) -> str:
        if isinstance(error, str):
            return error.strip()
        if isinstance(error, dict):
            code = error.get("code") or error.get("status")
            message = error.get("message") or error.get("detail")
            if isinstance(message, str) and message.strip():
                if isinstance(code, (str, int)) and str(code).strip():
                    return f"{code}: {message.strip()}"
                return message.strip()
            if isinstance(code, (str, int)):
                return str(code)
        return ""
