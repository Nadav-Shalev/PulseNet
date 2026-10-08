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

    def test_rejects_fields_over_100_chars(self):
        # The users columns are VARCHAR(100); the length check runs before the format checks.
        expected = {
            "name": "Name must be 100 characters or fewer",
            "username": "Username must be 100 characters or fewer",
            "email": "Email must be 100 characters or fewer",
        }
        for field, message in expected.items():
            with self.subTest(field=field):
                # Arrange
                payload = _valid_signup(**{field: "a" * 101})

                # Act
                _normalized, error = app._validate_signup_payload(payload)

                # Assert
                self.assertEqual(error, message)

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


class PayloadTypeTests(unittest.TestCase):
    def test_body_that_is_not_an_object_raises_input_error(self):
        for validate in (app._validate_signup_payload, app._validate_login_payload):
            with self.subTest(validate=validate.__name__):
                with self.assertRaises(app.InputError):
                    validate(["ada@example.com"])

    def test_missing_body_is_reported_as_missing_fields(self):
        _normalized, error = app._validate_login_payload(None)

        self.assertEqual(error, "email and password are required")

    def test_non_string_password_raises_instead_of_reaching_bcrypt(self):
        # A numeric password used to reach .encode() in _hash_password -> 500.
        with self.assertRaises(app.InputError) as ctx:
            app._validate_signup_payload(_valid_signup(password=12345678))

        self.assertEqual(str(ctx.exception), "password must be a string")

    def test_password_is_not_trimmed(self):
        normalized, error = app._validate_signup_payload(_valid_signup(password=" pw "))

        self.assertIsNone(error)
        self.assertEqual(normalized["password"], " pw ")



class PasswordRuleTests(unittest.TestCase):
    """bcrypt 5 raises ValueError past 72 bytes, so a longer password must be a 400
    before it reaches _hash_password, not a 500 inside it."""

    def test_empty_password_is_required(self):
        self.assertEqual(app._password_error(""), "password is required")

    def test_72_bytes_is_the_most_bcrypt_takes(self):
        self.assertIsNone(app._password_error("a" * 72))
        self.assertEqual(app._password_error("a" * 73), app.PASSWORD_TOO_LONG)

    def test_the_limit_counts_utf8_bytes_not_characters(self):
        # 37 Hebrew letters are 74 bytes in UTF-8: over the limit at 37 characters.
        self.assertEqual(app._password_error("א" * 37), app.PASSWORD_TOO_LONG)
        self.assertIsNone(app._password_error("א" * 36))

    def test_every_password_that_passes_can_be_hashed(self):
        for password in ("a" * 72, "א" * 36, "😀" * 18):
            with self.subTest(length=len(password)):
                self.assertIsNone(app._password_error(password))
                app._hash_password(password)   # no ValueError

    def test_signup_uses_the_rule(self):
        _normalized, error = app._validate_signup_payload(_valid_signup(password="x" * 73))

        self.assertEqual(error, app.PASSWORD_TOO_LONG)


if __name__ == "__main__":
    unittest.main()
