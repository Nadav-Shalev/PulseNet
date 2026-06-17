"""Unit tests for auth request validation helpers."""

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


def _valid_signup(**overrides):
    payload = {
        "name": "Ada Lovelace",
        "username": "ada",
        "email": "ada@example.com",
        "bio": "math",
        "password": "S3cret-pass!",
    }
    payload.update(overrides)
    return payload


class SignupValidationTests(unittest.TestCase):
    def test_rejects_missing_email(self):
        # Arrange
        payload = _valid_signup(email="")

        # Act
        normalized, error = app._validate_signup_payload(payload)

        # Assert
        self.assertEqual(normalized["email"], "")
        self.assertEqual(error, "name, username, and email are required")

    def test_rejects_missing_password(self):
        # Arrange
        payload = _valid_signup(password="")

        # Act
        _normalized, error = app._validate_signup_payload(payload)

        # Assert
        self.assertEqual(error, "password is required")

    def test_rejects_invalid_email(self):
        # Arrange
        payload = _valid_signup(email="not-an-email")

        # Act
        _normalized, error = app._validate_signup_payload(payload)

        # Assert
        self.assertEqual(error, "Invalid email format")

    def test_rejects_invalid_username(self):
        # Arrange
        payload = _valid_signup(username="bad user!")

        # Act
        _normalized, error = app._validate_signup_payload(payload)

        # Assert
        self.assertEqual(error, "Username may only contain letters, numbers, underscores, and dots")

    def test_accepts_valid_signup_and_trims_fields(self):
        # Arrange
        payload = _valid_signup(name=" Ada ", username=" ada ", email=" ada@example.com ", bio=" hi ")

        # Act
        normalized, error = app._validate_signup_payload(payload)

        # Assert
        self.assertIsNone(error)
        self.assertEqual(normalized["name"], "Ada")
        self.assertEqual(normalized["username"], "ada")
        self.assertEqual(normalized["email"], "ada@example.com")
        self.assertEqual(normalized["bio"], "hi")


class LoginValidationTests(unittest.TestCase):
    def test_rejects_missing_email(self):
        # Arrange
        payload = {"email": "", "password": "S3cret-pass!"}

        # Act
        _normalized, error = app._validate_login_payload(payload)

        # Assert
        self.assertEqual(error, "email and password are required")

    def test_rejects_missing_password(self):
        # Arrange
        payload = {"email": "ada@example.com", "password": ""}

        # Act
        _normalized, error = app._validate_login_payload(payload)

        # Assert
        self.assertEqual(error, "email and password are required")

    def test_accepts_valid_login_and_trims_email(self):
        # Arrange
        payload = {"email": " ada@example.com ", "password": "S3cret-pass!"}

        # Act
        normalized, error = app._validate_login_payload(payload)

        # Assert
        self.assertIsNone(error)
        self.assertEqual(normalized["email"], "ada@example.com")
        self.assertEqual(normalized["password"], "S3cret-pass!")


if __name__ == "__main__":
    unittest.main()
