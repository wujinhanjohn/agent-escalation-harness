"""Shared test isolation.

Every test gets a throwaway encryption key and a temp .env path so the suite
never encrypts with a real key or writes secrets into the repo working tree.
"""

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _isolate_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("HARNESS_ENV_PATH", str(tmp_path / ".env"))
