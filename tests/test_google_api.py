import base64
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from google_api import GoogleAPIError, GoogleVideoClient
from grok_api import make_video_path


VIDEO_BYTES = b"fake-google-mp4"


def completed_response(interaction_id="interaction-123"):
    return json.dumps(
        {
            "id": interaction_id,
            "status": "completed",
            "model": "gemini-omni-1.2-flash",
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "video",
                            "mime_type": "video/mp4",
                            "data": base64.b64encode(VIDEO_BYTES).decode("ascii"),
                        }
                    ],
                }
            ],
        }
    ).encode("utf-8")


class FakeResponse:
    def __init__(self, body: bytes):
        self.stream = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.stream.close()

    def read(self, size=-1):
        return self.stream.read(size)


class GoogleVideoClientTests(unittest.TestCase):
    def setUp(self):
        self.client = GoogleVideoClient("google-test-secret")

    @patch("google_api.urllib.request.urlopen")
    def test_text_to_video_payload_and_mp4_save(self, urlopen):
        urlopen.return_value = FakeResponse(completed_response())
        with tempfile.TemporaryDirectory() as directory:
            interaction_id, video = self.client.generate_video(
                prompt="Drone above the mountains",
                model="gemini-omni-1.2-flash",
                duration=10,
                aspect_ratio="16:9",
                resolution="720p",
            )
            target = make_video_path(Path(directory), interaction_id, prefix="google")
            saved = self.client.save_video(video, target)

            self.assertEqual(saved.read_bytes(), VIDEO_BYTES)
            self.assertTrue(saved.name.startswith("google_"))
            self.assertFalse(Path(str(saved) + ".part").exists())

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(request.get_header("X-goog-api-key"), "google-test-secret")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload,
            {
                "model": "gemini-omni-1.2-flash",
                "input": "Drone above the mountains",
                "response_format": {
                    "type": "video",
                    "duration": "10s",
                    "aspect_ratio": "16:9",
                    "resolution": "720p",
                },
                "store": False,
            },
        )

    @patch("google_api.urllib.request.urlopen")
    def test_image_to_video_contains_image_and_motion_prompt(self, urlopen):
        urlopen.return_value = FakeResponse(completed_response())
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "start.jpg"
            image.write_bytes(b"fake-jpeg")

            self.client.generate_video(
                prompt="Slowly zoom the camera in",
                model="gemini-omni-1.2-flash",
                duration=6,
                aspect_ratio="9:16",
                resolution="1080p",
                image_path=image,
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload["input"],
            [
                {
                    "type": "image",
                    "data": base64.b64encode(b"fake-jpeg").decode("ascii"),
                    "mime_type": "image/jpeg",
                },
                {"type": "text", "text": "Slowly zoom the camera in"},
            ],
        )
        self.assertEqual(payload["response_format"]["duration"], "6s")
        self.assertEqual(payload["response_format"]["aspect_ratio"], "9:16")

    @patch("google_api.urllib.request.urlopen")
    def test_missing_video_raises_clear_error(self, urlopen):
        urlopen.return_value = FakeResponse(
            b'{"id":"empty","status":"completed","steps":[{"type":"model_output","content":[]}]}'
        )

        with self.assertRaisesRegex(GoogleAPIError, "without an MP4 video"):
            self.client.generate_video(
                prompt="Test",
                model="gemini-omni-1.2-flash",
                duration=5,
                aspect_ratio="16:9",
                resolution="360p",
            )

    @patch("google_api.urllib.request.urlopen")
    def test_google_http_error_is_readable(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            403,
            "Forbidden",
            {},
            io.BytesIO(b'{"error":{"code":403,"message":"Billing is not enabled"}}'),
        )

        with self.assertRaisesRegex(GoogleAPIError, "HTTP 403.*Billing is not enabled.*billing"):
            self.client.generate_video(
                prompt="Test",
                model="gemini-omni-1.2-flash",
                duration=5,
                aspect_ratio="16:9",
                resolution="720p",
            )

    def test_rejects_google_unsupported_duration(self):
        with self.assertRaisesRegex(GoogleAPIError, "3 and 15"):
            self.client.generate_video(
                prompt="Test",
                model="gemini-omni-1.2-flash",
                duration=2,
                aspect_ratio="16:9",
                resolution="720p",
            )


if __name__ == "__main__":
    unittest.main()
