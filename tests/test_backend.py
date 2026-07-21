"""Backend endpoint tests using FastAPI's TestClient against a temp SQLite DB."""

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient backed by a fresh throwaway DB per test."""
    monkeypatch.setenv("HARNESS_DB", str(tmp_path / "test.db"))
    # Reimport so the db module picks up the temp path cleanly, then init.
    from harness import app as app_module

    importlib.reload(app_module)
    app_module.db.init_db()
    with TestClient(app_module.app) as c:
        yield c


SCHEMA = [
    {"name": "SUPABASE_URL", "type": "string", "secret": False, "required": True},
    {"name": "SUPABASE_ANON_KEY", "type": "string", "secret": False, "required": True},
    {"name": "SUPABASE_SERVICE_KEY", "type": "secret", "secret": True, "required": True},
]


def _create(client, category="provisioning"):
    resp = client.post(
        "/requests",
        json={
            "title": "Create Supabase project",
            "context": "Building auth for the todo app.",
            "instructions": "1. New project  2. Paste values",
            "response_schema": SCHEMA,
            "category": category,
        },
    )
    assert resp.status_code == 200
    return resp.json()


def test_create_then_get_returns_pending(client):
    created = _create(client)
    assert created["status"] == "pending"
    assert created["id"].startswith("req_")

    got = client.get(f"/requests/{created['id']}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "pending"
    assert body["response"] is None
    assert body["title"] == "Create Supabase project"
    assert len(body["response_schema"]) == 3


def test_list_pending(client):
    _create(client)
    _create(client)
    resp = client.get("/api/requests?status=pending")
    assert resp.status_code == 200
    reqs = resp.json()["requests"]
    assert len(reqs) == 2
    assert all(r["status"] == "pending" for r in reqs)


def test_resolve_sets_response_and_get_returns_it(client):
    created = _create(client)
    values = {
        "SUPABASE_URL": "https://abc.supabase.co",
        "SUPABASE_ANON_KEY": "anon-123",
        "SUPABASE_SERVICE_KEY": "service-456",
    }
    resolved = client.post(
        f"/requests/{created['id']}/resolve", json={"response": values}
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["response"] == values
    assert body["resolved_at"] is not None

    got = client.get(f"/requests/{created['id']}").json()
    assert got["status"] == "resolved"
    assert got["response"] == values


def test_resolve_missing_required_field_returns_400(client):
    created = _create(client)
    resolved = client.post(
        f"/requests/{created['id']}/resolve",
        json={"response": {"SUPABASE_URL": "https://abc.supabase.co"}},
    )
    assert resolved.status_code == 400
    assert "SUPABASE_ANON_KEY" in resolved.json()["detail"]


def test_resolve_unknown_id_returns_404(client):
    resp = client.post(
        "/requests/req_zzzz/resolve", json={"response": {"x": "y"}}
    )
    assert resp.status_code == 404


def test_resolve_already_resolved_returns_404(client):
    created = _create(client)
    values = {
        "SUPABASE_URL": "u",
        "SUPABASE_ANON_KEY": "a",
        "SUPABASE_SERVICE_KEY": "s",
    }
    first = client.post(
        f"/requests/{created['id']}/resolve", json={"response": values}
    )
    assert first.status_code == 200
    second = client.post(
        f"/requests/{created['id']}/resolve", json={"response": values}
    )
    assert second.status_code == 404


def test_get_unknown_id_returns_404(client):
    assert client.get("/requests/req_nope").status_code == 404


def test_stats_counts_are_correct(client):
    a = _create(client, category="provisioning")
    _create(client, category="provisioning")
    _create(client, category="api-key")

    # Resolve one of them.
    client.post(
        f"/requests/{a['id']}/resolve",
        json={
            "response": {
                "SUPABASE_URL": "u",
                "SUPABASE_ANON_KEY": "an",
                "SUPABASE_SERVICE_KEY": "sv",
            }
        },
    )

    stats = client.get("/api/stats").json()
    assert stats["total"] == 3
    assert stats["pending"] == 2
    assert stats["resolved"] == 1
    assert stats["by_category"]["provisioning"]["total"] == 2
    assert stats["by_category"]["provisioning"]["resolved"] == 1
    assert stats["by_category"]["api-key"]["total"] == 1
    assert stats["top_category"] == "provisioning"
    assert stats["avg_resolve_seconds"] is not None
