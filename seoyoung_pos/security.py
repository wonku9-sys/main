"""Password hashing without additional runtime dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


ITERATIONS = 600_000


def validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("비밀번호는 8자 이상 입력해 주세요.")
    if len(password) > 1024:
        raise ValueError("비밀번호는 1,024자 이내로 입력해 주세요.")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "$".join(("pbkdf2_sha256", str(ITERATIONS),
                     base64.b64encode(salt).decode("ascii"),
                     base64.b64encode(digest).decode("ascii")))


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_text, expected_text = encoded.split("$")
        iterations = int(rounds)
        if scheme != "pbkdf2_sha256" or not 100_000 <= iterations <= 2_000_000:
            return False
        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(expected_text, validate=True)
        if len(salt) != 16 or len(expected) != 32 or len(password) > 1024:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False
