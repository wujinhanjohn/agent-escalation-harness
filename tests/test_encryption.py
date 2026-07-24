"""Tests for encryption of the response at rest (harness/crypto.py + db.py)."""

import importlib

import pytest


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A fresh db module bound to a throwaway SQLite file."""
    monkeypatch.setenv("HARNESS_DB", str(tmp_path / "enc.db"))
    from harness import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    return db_module


SCHEMA = [{"name": "SECRET_KEY", "secret": True, "required": True}]


def test_response_is_encrypted_on_disk(db, tmp_path):
    rec = db.create_request(
        title="t", context="", instructions="",
        response_schema=SCHEMA, category="provisioning",
    )
    db.resolve_request(rec["id"], {"SECRET_KEY": "super_secret_value"})

    # Read the raw column straight from the SQLite file, bypassing our decode.
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "enc.db"))
    raw = conn.execute(
        "SELECT response FROM requests WHERE id=?", (rec["id"],)
    ).fetchone()[0]
    conn.close()

    # The plaintext secret must not be present in the stored bytes.
    assert "super_secret_value" not in raw
    assert raw is not None and len(raw) > 0


def test_roundtrip_decrypts_correctly(db):
    rec = db.create_request(
        title="t", context="", instructions="",
        response_schema=SCHEMA, category="provisioning",
    )
    db.resolve_request(rec["id"], {"SECRET_KEY": "super_secret_value"})
    got = db.get_request(rec["id"])
    assert got["response"] == {"SECRET_KEY": "super_secret_value"}


def test_crypto_roundtrip():
    from harness import crypto

    token = crypto.encrypt("hello secret")
    assert token != "hello secret"
    assert crypto.decrypt(token) == "hello secret"
