"""Unit tests for password hashing and verification helpers."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
BACKEND_DIR = TESTS_DIR.parent
for _p in (BACKEND_DIR, TESTS_DIR, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import app  # noqa: E402


class PasswordHashingTests(unittest.TestCase):
    def test_hash_password_does_not_store_plain_password(self):
        # Arrange
        password = "S3cret-pass!"

        # Act
        hashed = app._hash_password(password)

        # Assert
        self.assertNotEqual(hashed, password)
        self.assertNotIn(password, hashed)

    def test_correct_password_passes_verification(self):
        # Arrange
        password = "S3cret-pass!"
        hashed = app._hash_password(password)

        # Act
        verified = app._verify_password(password, hashed)

        # Assert
        self.assertTrue(verified)

    def test_wrong_password_fails_verification(self):
        # Arrange
        hashed = app._hash_password("S3cret-pass!")

        # Act
        verified = app._verify_password("wrong-pass", hashed)

        # Assert
        self.assertFalse(verified)

    def test_same_password_hashes_differ_because_of_salt(self):
        # Arrange
        password = "S3cret-pass!"

        # Act
        first = app._hash_password(password)
        second = app._hash_password(password)

        # Assert
        self.assertNotEqual(first, second)
        self.assertTrue(app._verify_password(password, first))
        self.assertTrue(app._verify_password(password, second))


if __name__ == "__main__":
    unittest.main()
