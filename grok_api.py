"""Small client for the official xAI video-generation REST API."""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable

from image_input import encode_image


API_BASE_URL = "https://api.x.ai/v1"
USER_AGENT = "AIVideoMaker/2.0"

VIDEO_MODELS = {
    "grok-imagine-video-1.5": {
        "label": "Grok Imagine 1.5 (best quality)",
        "resolutions": ("480p", "720p", "1080p"),
    },
    "grok-imagine-video-1.5-lite": {
        "label": "Grok Imagine 1.5 Lite (cheaper)",
        "resolutions": ("480p", "720p", "1080p"),
    },
    "grok-imagine-video": {
        "label": "Grok Imagine Video (legacy, up to 720p)",
        "resolutions": ("480p", "720p"),
    },
}

ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9", "5:2")


class GrokAPIError(Exception):
    """An error that can be shown directly in the user interface."""


class GrokVideoClient:
    def __init__(self, api_key: str, request_timeout: int = 60) -> None:
        self.api_key = api_key.strip()
        self.request_timeout = request_timeout

    def create_video(
        self,
        *,
        prompt: str,
        model: str,
        duration: int,
        aspect_ratio: str,
        resolution: str,
        generate_audio: bool,
        image_path: Path | None = None,
    ) -> str:
        if not self.api_key:
            raise GrokAPIError("Enter your xAI API key.")
        if not prompt.strip():
            raise GrokAPIError("The prompt must not be empty.")
        if model not in VIDEO_MODELS:
            raise GrokAPIError("The selected model is not supported.")
        if not 1 <= duration <= 15:
            raise GrokAPIError("Duration must be between 1 and 15 seconds.")
        if aspect_ratio not in ASPECT_RATIOS:
            raise GrokAPIError("The selected aspect ratio is not supported.")
        if resolution not in VIDEO_MODELS[model]["resolutions"]:
            raise GrokAPIError("The selected resolution is not supported for this model.")

        payload = {
            "model": model,
            "prompt": prompt.strip(),
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "generate_audio": generate_audio,
        }
        if image_path is not None:
            image_data, mime_type = encode_image(image_path)
            payload["image"] = {"url": f"data:{mime_type};base64,{image_data}"}
            # xAI image-to-video always follows the source image's aspect ratio.
            payload.pop("aspect_ratio")
        data = self._request_json("POST", "/videos/generations", payload)
        request_id = data.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            raise GrokAPIError("xAI did not return a video generation request ID.")
        return request_id.strip()

    def wait_for_video(
        self,
        request_id: str,
        *,
        progress_callback: Callable[[str], None] | None = None,
        timeout: int = 20 * 60,
        poll_interval: int = 5,
    ) -> str:
        deadline = time.monotonic() + timeout
        quoted_id = urllib.parse.quote(request_id, safe="")

        while True:
            data = self._request_json("GET", f"/videos/{quoted_id}")
            status = data.get("status")

            if status == "done":
                video = data.get("video")
                video_url = video.get("url") if isinstance(video, dict) else None
                if not isinstance(video_url, str) or not video_url.strip():
                    raise GrokAPIError(
                        "The video is ready, but xAI did not return a download URL."
                    )
                return video_url.strip()

            if status in ("failed", "expired"):
                detail = self._error_detail(data.get("error"))
                message = "Video generation failed"
                if status == "expired":
                    message = "The video generation request expired"
                if detail:
                    message += f": {detail}"
                else:
                    message += "."
                raise GrokAPIError(message)

            if time.monotonic() >= deadline:
                raise GrokAPIError(
                    "Generation is taking longer than 20 minutes. Check the request "
                    f"in the xAI console (ID: {request_id})."
                )

            if progress_callback:
                progress_callback("Grok is still generating the video…")
            time.sleep(poll_interval)

    def download_video(self, video_url: str, target: Path) -> Path:
        parsed = urllib.parse.urlparse(video_url)
        if parsed.scheme not in ("http", "https"):
            raise GrokAPIError("The video URL is not a valid HTTP/HTTPS URL.")

        target = Path(target)
        partial = target.with_name(target.name + ".part")
        request = urllib.request.Request(video_url, headers={"User-Agent": USER_AGENT})

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(request, timeout=120) as response:
                with partial.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
            partial.replace(target)
            return target
        except Exception as exc:
            partial.unlink(missing_ok=True)
            if isinstance(exc, urllib.error.HTTPError):
                raise GrokAPIError(
                    f"Video download failed (HTTP {exc.code}: {exc.reason})."
                ) from exc
            if isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError)):
                raise GrokAPIError(f"Video download failed: {exc}") from exc
            if isinstance(exc, OSError):
                raise GrokAPIError(f"Could not save the video to disk: {exc}") from exc
            raise

    def _request_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": USER_AGENT,
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            API_BASE_URL + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            detail = self._error_detail_from_response(raw)
            message = f"xAI API error (HTTP {exc.code})"
            if detail:
                message += f": {detail}"
            if exc.code in (401, 403):
                message += ". Check your API key and xAI API access"
            elif exc.code == 429:
                message += ". Too many requests or insufficient credit; wait and try again"
            if detail or exc.code in (401, 403, 429):
                message += "."
            raise GrokAPIError(message) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise GrokAPIError(f"Could not connect to the xAI API: {exc}") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GrokAPIError("The xAI API returned an unreadable response.") from None
        if not isinstance(data, dict):
            raise GrokAPIError("The xAI API returned an unexpected response.")
        return data

    @staticmethod
    def _error_detail_from_response(raw: bytes) -> str:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            text = raw.decode("utf-8", errors="replace").strip()
            return text[:500]
        if isinstance(data, dict):
            return GrokVideoClient._error_detail(data.get("error", data.get("message")))
        return ""

    @staticmethod
    def _error_detail(error: object) -> str:
        if isinstance(error, str):
            return error.strip()
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message") or error.get("detail")
            if isinstance(message, str) and message.strip():
                if isinstance(code, str) and code.strip():
                    return f"{code.strip()}: {message.strip()}"
                return message.strip()
            if isinstance(code, str):
                return code.strip()
        return ""


def make_video_path(output_dir: Path, request_id: str, prefix: str = "grok") -> Path:
    """Create a unique, filesystem-safe MP4 path for a finished request."""
    output_dir = Path(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", request_id)[:12] or "video"
    safe_prefix = re.sub(r"[^A-Za-z0-9_-]", "", prefix) or "video"
    candidate = output_dir / f"{safe_prefix}_{timestamp}_{safe_id}.mp4"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{safe_prefix}_{timestamp}_{safe_id}_{counter}.mp4"
        counter += 1
    return candidate
