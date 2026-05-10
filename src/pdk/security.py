from __future__ import annotations

import base64
import getpass
import os
from pathlib import Path
from typing import Any

from .privacy import detect_private_data, private_warning_labels


ENCRYPTED_MAGIC = b"PDKENC1\n"


class SecurityError(Exception):
    pass


def secret_warnings(text: str) -> list[str]:
    return private_warning_labels(text)


def redact_text(text: str) -> str:
    redacted = text
    for finding in reversed(detect_private_data(text)):
        redacted = redacted[: finding.start] + "[REDACTED]" + redacted[finding.end :]
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value


def is_encrypted_database(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("rb") as file:
        return file.read(len(ENCRYPTED_MAGIC)) == ENCRYPTED_MAGIC


def require_plain_database(path: Path) -> None:
    if is_encrypted_database(path):
        raise SecurityError("global store is encrypted; run `pdk security unlock` first")


def _cryptography():
    try:
        from cryptography.fernet import Fernet, InvalidToken
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency packaging guard
        raise SecurityError("encryption requires the cryptography package") from exc
    return Fernet, InvalidToken, hashes, PBKDF2HMAC


def _passphrase(confirm: bool = False) -> bytes:
    value = getpass.getpass("Passphrase: ")
    if confirm:
        repeated = getpass.getpass("Confirm passphrase: ")
        if value != repeated:
            raise SecurityError("passphrases do not match")
    if not value:
        raise SecurityError("passphrase cannot be empty")
    return value.encode("utf-8")


def _derive_key(passphrase: bytes, salt: bytes) -> bytes:
    _, _, hashes, PBKDF2HMAC = _cryptography()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase))


def encrypt_database(path: Path, *, passphrase: bytes | None = None) -> None:
    if not path.exists():
        raise SecurityError(f"database does not exist: {path}")
    if is_encrypted_database(path):
        raise SecurityError("global store is already encrypted")
    Fernet, _, _, _ = _cryptography()
    salt = os.urandom(16)
    key = _derive_key(passphrase or _passphrase(confirm=True), salt)
    token = Fernet(key).encrypt(path.read_bytes())
    path.write_bytes(ENCRYPTED_MAGIC + salt + token)


def decrypt_database(path: Path, *, passphrase: bytes | None = None) -> None:
    if not path.exists():
        raise SecurityError(f"database does not exist: {path}")
    raw = path.read_bytes()
    if not raw.startswith(ENCRYPTED_MAGIC):
        raise SecurityError("global store is not encrypted")
    Fernet, InvalidToken, _, _ = _cryptography()
    salt_start = len(ENCRYPTED_MAGIC)
    salt_end = salt_start + 16
    salt = raw[salt_start:salt_end]
    token = raw[salt_end:]
    key = _derive_key(passphrase or _passphrase(), salt)
    try:
        plaintext = Fernet(key).decrypt(token)
    except InvalidToken as exc:
        raise SecurityError("could not decrypt global store; check passphrase") from exc
    path.write_bytes(plaintext)
