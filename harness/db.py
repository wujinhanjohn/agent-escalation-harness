"""SQLite persistence for escalation requests (stdlib sqlite3, no ORM).

One table, ``requests``. JSON-shaped columns (``response_schema`` and
``response``) are stored as TEXT and (de)serialized here so the rest of the
app deals in plain dicts. The DB path comes from ``HARNESS_DB`` so tests can
point at a temp file and stay isolated.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


def _db_path() -> str:
    return os.environ.get("HARNESS_DB", "harness.db")


def _now() -> str:
    """UTC timestamp, ISO-8601 with a trailing Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the requests table if it does not exist."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                context         TEXT NOT NULL DEFAULT '',
                instructions    TEXT NOT NULL DEFAULT '',
                response_schema TEXT NOT NULL,
                category        TEXT NOT NULL DEFAULT 'general',
                status          TEXT NOT NULL DEFAULT 'pending',
                response        TEXT,
                created_at      TEXT NOT NULL,
                resolved_at     TEXT
            )
            """
        )


def _new_id() -> str:
    """A short, human-readable request id like ``req_a1b2``."""
    return "req_" + secrets.token_hex(2)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "context": row["context"],
        "instructions": row["instructions"],
        "response_schema": json.loads(row["response_schema"]),
        "category": row["category"],
        "status": row["status"],
        "response": json.loads(row["response"]) if row["response"] else None,
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def create_request(
    *,
    title: str,
    context: str,
    instructions: str,
    response_schema: list[dict[str, Any]],
    category: str,
) -> dict[str, Any]:
    """Insert a new pending request and return the full record."""
    req_id = _new_id()
    created_at = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO requests
                (id, title, context, instructions, response_schema,
                 category, status, response, created_at, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, NULL)
            """,
            (
                req_id,
                title,
                context,
                instructions,
                json.dumps(response_schema),
                category,
                created_at,
            ),
        )
    return get_request(req_id)  # type: ignore[return-value]


def get_request(req_id: str) -> Optional[dict[str, Any]]:
    """Return the full record for ``req_id`` or None if it does not exist."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM requests WHERE id = ?", (req_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_requests(status: Optional[str] = None) -> list[dict[str, Any]]:
    """List requests, optionally filtered by status, newest first."""
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM requests WHERE status = ? "
                "ORDER BY created_at DESC, id DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY created_at DESC, id DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def resolve_request(
    req_id: str, response: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Persist the human's ``response`` and mark the request resolved.

    Returns the updated record, or None if the id is unknown or the request
    is already resolved (the caller maps that to a 404).
    """
    existing = get_request(req_id)
    if existing is None or existing["status"] != "pending":
        return None
    resolved_at = _now()
    with _connect() as conn:
        conn.execute(
            "UPDATE requests SET status='resolved', response=?, resolved_at=? "
            "WHERE id=?",
            (json.dumps(response), resolved_at, req_id),
        )
    return get_request(req_id)


def stats() -> dict[str, Any]:
    """Aggregate counts by category and status, plus average resolve time.

    The category breakdown is the instrumentation payload: it answers "which
    wall do I hit most" across every escalation ever logged.
    """
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM requests").fetchall()

    records = [_row_to_dict(r) for r in rows]
    pending = sum(1 for r in records if r["status"] == "pending")
    resolved = sum(1 for r in records if r["status"] == "resolved")

    by_category: dict[str, dict[str, int]] = {}
    for r in records:
        cat = by_category.setdefault(
            r["category"], {"total": 0, "pending": 0, "resolved": 0}
        )
        cat["total"] += 1
        cat[r["status"]] = cat.get(r["status"], 0) + 1

    # Average seconds between created_at and resolved_at over resolved rows.
    durations: list[float] = []
    for r in records:
        if r["status"] == "resolved" and r["resolved_at"]:
            start = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            end = datetime.strptime(r["resolved_at"], "%Y-%m-%dT%H:%M:%SZ")
            durations.append((end - start).total_seconds())
    avg_resolve_seconds = round(sum(durations) / len(durations), 1) if durations else None

    top_category = (
        max(by_category.items(), key=lambda kv: kv[1]["total"])[0]
        if by_category
        else None
    )

    return {
        "total": len(records),
        "pending": pending,
        "resolved": resolved,
        "by_category": by_category,
        "top_category": top_category,
        "avg_resolve_seconds": avg_resolve_seconds,
    }
