"""Symmetric encryption for secrets at rest.

Only the human-submitted ``response`` (which can hold API keys and tokens) is
encrypted in SQLite; everything else stays plaintext so the inbox and stats
stay legible. Uses Fernet (AES-128-CBC + HMAC) from ``cryptography``.

Key resolution, in order:
  1. ``HARNESS_SECRET_KEY``  - a base64 Fernet key in the environment. Use this
     to source the key from an OS keychain or secret manager.
  2. ``HARNESS_KEY_FILE``    - a file holding the key (default ``.harness_key``).
     Auto-created with 0600 perms on first use so encryption works with zero
     config. The file is gitignored; keep it out of backups you share.

The key is deliberately separable from the database file: a stolen or
committed ``harness.db`` is useless without the key.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet


def _load_key() -> bytes:
    """Return the Fernet key from env, or a key file, creating one if needed."""
    env_key = os.environ.get("HARNESS_SECRET_KEY")
    if env_key:
        return env_key.encode()

    key_path = Path(os.environ.get("HARNESS_KEY_FILE", ".harness_key"))
    if key_path.exists():
        return key_path.read_bytes().strip()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    os.chmod(key_path, 0o600)
    return key


def _cipher() -> Fernet:
    # Constructed per call (cheap) rather than cached, so a changed key or
    # env var takes effect immediately - important for test isolation.
    return Fernet(_load_key())


def encrypt(plaintext: str) -> str:
    """Encrypt a string, returning a Fernet token as text."""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token back to the original string."""
    return _cipher().decrypt(token.encode()).decode()
