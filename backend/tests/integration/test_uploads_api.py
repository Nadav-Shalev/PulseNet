"""Image upload API tests: POST /api/upload and GET /uploads/<filename>.

Focus: uploads need a session, only real images with a matching extension are
stored, the file gets a random server-side name, oversized bodies get a JSON 413,
and serving cannot escape the upload folder. UPLOAD_DIR is redirected to a temp
folder so the tests never touch backend/uploads/.
"""

import os
import re
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from support import FakeConn, client, db_down, patch_db  # noqa: E402

import app  # noqa: E402


def _png_bytes():
    out = BytesIO()
    Image.new("RGB", (1, 1), color="white").save(out, format="PNG")
    return out.getvalue()


def _session_user():
    return {
        "id": 42, "name": "Ada", "username": "ada", "email": "ada@example.com",
        "bio": "hi", "avatar": "a.svg", "profile_image": "p.svg",
    }


def _authed_client(sid="valid-sid"):
    c = client()
    c.set_cookie("session_id", sid)
    return c


class _TempUploadDir(unittest.TestCase):
    """Points app.UPLOAD_DIR at <tmp>/uploads; <tmp> itself plays the backend folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.upload_dir = os.path.join(self.root, "uploads")
        os.makedirs(self.upload_dir)
        patcher = patch.object(app, "UPLOAD_DIR", self.upload_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def stored_files(self):
        return os.listdir(self.upload_dir)


class UploadTests(_TempUploadDir):
    def _upload(self, data, filename="pic.png", field="file"):
        conn = FakeConn(fetchone=[_session_user()])
        form = {field: (BytesIO(data), filename)}
        with patch_db(conn):
            return _authed_client().post(
                "/api/upload", data=form, content_type="multipart/form-data"
            )

    def test_upload_requires_session(self):
        resp = client().post(
            "/api/upload",
            data={"file": (BytesIO(_png_bytes()), "pic.png")},
            content_type="multipart/form-data",
        )

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.stored_files(), [])

    def test_upload_with_db_down_returns_503(self):
        # The session can't be checked without the DB, so the upload is refused.
        with db_down():
            resp = _authed_client().post(
                "/api/upload",
                data={"file": (BytesIO(_png_bytes()), "pic.png")},
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(self.stored_files(), [])

    def test_valid_png_is_stored_under_a_random_name(self):
        resp = self._upload(_png_bytes(), filename="../../My Photo.png")

        self.assertEqual(resp.status_code, 201)
        url = resp.get_json()["url"]
        match = re.search(r"/uploads/([0-9a-f]{32}\.png)$", url)
        self.assertIsNotNone(match, url)
        # The client's filename (with its path tricks) is never used on disk.
        self.assertEqual(self.stored_files(), [match.group(1)])
        with open(os.path.join(self.upload_dir, match.group(1)), "rb") as saved:
            self.assertEqual(saved.read(), _png_bytes())

    def test_missing_file_field_returns_400(self):
        resp = self._upload(_png_bytes(), field="image")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("file", resp.get_json()["error"])

    def test_disallowed_extension_returns_400(self):
        resp = self._upload(_png_bytes(), filename="pic.svg")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.stored_files(), [])

    def test_text_disguised_as_png_returns_400(self):
        resp = self._upload(b"<html>not an image</html>", filename="pic.png")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("not a valid image", resp.get_json()["error"])
        self.assertEqual(self.stored_files(), [])

    def test_oversized_request_returns_json_413(self):
        # A raw body (not data={...}): the test client spools a large multipart
        # form to a temp file it never closes when the request is rejected.
        too_big = b"\x00" * (app.app.config["MAX_CONTENT_LENGTH"] + 1)
        conn = FakeConn(fetchone=[_session_user()])
        with patch_db(conn):
            resp = _authed_client().post(
                "/api/upload", data=too_big,
                content_type="multipart/form-data; boundary=x",
            )

        self.assertEqual(resp.status_code, 413)
        self.assertIn("too large", resp.get_json()["error"].lower())
        self.assertEqual(self.stored_files(), [])


class ServeUploadTests(_TempUploadDir):
    def test_serves_a_stored_file(self):
        with open(os.path.join(self.upload_dir, "abc.png"), "wb") as f:
            f.write(_png_bytes())

        resp = client().get("/uploads/abc.png")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/png")
        self.assertEqual(resp.data, _png_bytes())
        resp.close()

    def test_unknown_file_returns_404(self):
        resp = client().get("/uploads/missing.png")

        self.assertEqual(resp.status_code, 404)

    def test_cannot_read_files_outside_the_upload_folder(self):
        with open(os.path.join(self.root, "secret.txt"), "w") as f:
            f.write("db password")

        for path in ("/uploads/../secret.txt", "/uploads/%2e%2e/secret.txt"):
            with self.subTest(path=path):
                resp = client().get(path)
                self.assertEqual(resp.status_code, 404)
                self.assertNotIn(b"db password", resp.data)


if __name__ == "__main__":
    unittest.main()
