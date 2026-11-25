import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from grok_api import GrokAPIError, GrokVideoClient, make_video_path


class FakeResponse:
    def __init__(self, body: bytes):
        self.stream = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.stream.close()

    def read(self, size=-1):
        return self.stream.read(size)


class GrokVideoClientTests(unittest.TestCase):
    def setUp(self):
        self.client = GrokVideoClient("test-secret")

    @patch("grok_api.urllib.request.urlopen")
    def test_create_video_sends_options_without_exposing_key_in_payload(self, urlopen):
        urlopen.return_value = FakeResponse(b'{"request_id":"request-123"}')

        request_id = self.client.create_video(
            prompt="Cat on the roof",
            model="grok-imagine-video-1.5",
            duration=8,
            aspect_ratio="16:9",
            resolution="720p",
            generate_audio=False,
        )

        self.assertEqual(request_id, "request-123")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.x.ai/v1/videos/generations")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload,
            {
                "model": "grok-imagine-video-1.5",
                "prompt": "Cat on the roof",
                "duration": 8,
                "aspect_ratio": "16:9",
                "resolution": "720p",
                "generate_audio": False,
            },
        )

    @patch("grok_api.urllib.request.urlopen")
    def test_create_image_to_video_sends_data_uri_and_omits_aspect_ratio(self, urlopen):
        urlopen.return_value = FakeResponse(b'{"request_id":"image-request"}')
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "start.png"
            image.write_bytes(b"fake-png-bytes")

            request_id = self.client.create_video(
                prompt="Slowly zoom in",
                model="grok-imagine-video-1.5",
                duration=8,
                aspect_ratio="16:9",
                resolution="1080p",
                generate_audio=True,
                image_path=image,
            )

        self.assertEqual(request_id, "image-request")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["image"]["url"], "data:image/png;base64,ZmFrZS1wbmctYnl0ZXM=")
        self.assertNotIn("aspect_ratio", payload)
        self.assertEqual(payload["resolution"], "1080p")

    @patch("grok_api.time.sleep", return_value=None)
    def test_wait_for_video_polls_until_done(self, _sleep):
        self.client._request_json = Mock(
            side_effect=[
                {"status": "pending"},
                {
                    "status": "done",
                    "video": {"url": "https://example.test/video.mp4"},
                },
            ]
        )

        result = self.client.wait_for_video("request-123", poll_interval=0)

        self.assertEqual(result, "https://example.test/video.mp4")
        self.assertEqual(self.client._request_json.call_count, 2)

    def test_failed_generation_returns_api_error_message(self):
        self.client._request_json = Mock(
            return_value={
                "status": "failed",
                "error": {"code": "invalid_argument", "message": "Prompt was blocked."},
            }
        )

        with self.assertRaisesRegex(GrokAPIError, "invalid_argument: Prompt was blocked"):
            self.client.wait_for_video("request-123")

    @patch("grok_api.urllib.request.urlopen")
    def test_download_video_replaces_partial_file(self, urlopen):
        urlopen.return_value = FakeResponse(b"fake-mp4-content")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "video.mp4"

            saved = self.client.download_video("https://example.test/video.mp4", target)

            self.assertEqual(saved, target)
            self.assertEqual(target.read_bytes(), b"fake-mp4-content")
            self.assertFalse(Path(str(target) + ".part").exists())

    @patch("grok_api.urllib.request.urlopen")
    def test_http_error_is_readable(self, urlopen):
        error = urllib.error.HTTPError(
            "https://api.x.ai/v1/videos/generations",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":{"message":"Invalid API key"}}'),
        )
        urlopen.side_effect = error

        with self.assertRaisesRegex(GrokAPIError, "HTTP 401.*Invalid API key"):
            self.client.create_video(
                prompt="Test",
                model="grok-imagine-video-1.5",
                duration=5,
                aspect_ratio="16:9",
                resolution="480p",
                generate_audio=True,
            )

    def test_video_path_has_safe_unique_name(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            first = make_video_path(output, "id/with:unsafe?characters")
            first.touch()
            second = make_video_path(output, "id/with:unsafe?characters")
            google = make_video_path(output, "interaction-123", prefix="google")

            self.assertNotIn("/", first.name)
            self.assertNotIn("?", first.name)
            self.assertTrue(first.name.endswith(".mp4"))
            self.assertNotEqual(first, second)
            self.assertTrue(google.name.startswith("google_"))


if __name__ == "__main__":
    unittest.main()
