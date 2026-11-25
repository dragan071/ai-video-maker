import base64
import tempfile
import unittest
from pathlib import Path

from image_input import ImageInputError, encode_image


class ImageInputTests(unittest.TestCase):
    def test_encodes_supported_image_with_correct_mime_type(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "photo.WEBP"
            image.write_bytes(b"webp-data")

            encoded, mime_type = encode_image(image)

            self.assertEqual(mime_type, "image/webp")
            self.assertEqual(base64.b64decode(encoded), b"webp-data")

    def test_rejects_unsupported_or_missing_image(self):
        with tempfile.TemporaryDirectory() as directory:
            text = Path(directory) / "notes.txt"
            text.write_text("not an image", encoding="utf-8")
            with self.assertRaisesRegex(ImageInputError, "PNG, JPEG or WebP"):
                encode_image(text)
            with self.assertRaisesRegex(ImageInputError, "does not exist"):
                encode_image(Path(directory) / "missing.png")


if __name__ == "__main__":
    unittest.main()
