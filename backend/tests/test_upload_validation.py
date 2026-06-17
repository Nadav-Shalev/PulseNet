import sys
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import _validate_image_upload, MAX_UPLOAD_BYTES  # noqa: E402


def _image_bytes(image_format):
    output = BytesIO()
    Image.new("RGB", (1, 1), color="white").save(output, format=image_format)
    return output.getvalue()


class UploadValidationTests(unittest.TestCase):
    def test_valid_small_png_upload_succeeds(self):
        detected = _validate_image_upload("avatar.png", _image_bytes("PNG"))

        self.assertEqual(detected, "PNG")

    def test_fake_png_with_text_content_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a valid image"):
            _validate_image_upload("avatar.png", b"<html>not an image</html>")

    def test_disallowed_extension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported file type"):
            _validate_image_upload("avatar.txt", _image_bytes("PNG"))

    def test_extension_must_match_detected_format(self):
        with self.assertRaisesRegex(ValueError, "extension does not match"):
            _validate_image_upload("avatar.png", _image_bytes("JPEG"))

    def test_jpeg_accepted_for_jpg_and_jpeg_extensions(self):
        self.assertEqual(_validate_image_upload("a.jpg", _image_bytes("JPEG")), "JPEG")
        self.assertEqual(_validate_image_upload("a.jpeg", _image_bytes("JPEG")), "JPEG")

    def test_gif_upload_accepted(self):
        self.assertEqual(_validate_image_upload("a.gif", _image_bytes("GIF")), "GIF")

    def test_webp_upload_accepted(self):
        self.assertEqual(_validate_image_upload("a.webp", _image_bytes("WEBP")), "WEBP")

    def test_empty_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            _validate_image_upload("avatar.png", b"")

    def test_oversized_file_is_rejected(self):
        # One byte over the limit; size is checked before image parsing.
        with self.assertRaisesRegex(ValueError, "larger than 5 MB"):
            _validate_image_upload("avatar.png", b"\x00" * (MAX_UPLOAD_BYTES + 1))

    def test_svg_extension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported file type"):
            _validate_image_upload("avatar.svg", b"<svg xmlns='x'></svg>")


if __name__ == "__main__":
    unittest.main()
