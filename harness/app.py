"""FastAPI backend + inbox for the agent escalation harness.

Three consumers share this one process:
  - the MCP server / agent, which POSTs requests and polls GET /requests/{id}
  - the inbox page (served at /), which reads /api/requests and POSTs resolves
  - /api/stats, the instrumentation view aggregating walls by category
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db
from .models import normalize_schema, validate_response

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Ensure the requests table exists before serving anything."""
    db.init_db()
    yield


app = FastAPI(title="Agent Escalation Harness", lifespan=_lifespan)


# --------------------------------------------------------------------------- #
# Request/response bodies
# --------------------------------------------------------------------------- #
class CreateRequest(BaseModel):
    title: str
    context: str = ""
    instructions: str = ""
    response_schema: list[dict[str, Any]]
    category: str = "general"


class ResolveRequest(BaseModel):
    # The human's field name -> value map. Validated against the request's
    # stored schema, not accepted blindly.
    response: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def _notify(record: dict[str, Any]) -> None:
    """Alert a human that a new wall needs them.

    Always prints a console banner with a terminal bell. If NTFY_TOPIC is set,
    also fire a best-effort push to ntfy.sh. A notification failure must never
    break request creation, so ntfy errors are swallowed.
    """
    bell = "\a"
    print(
        f"{bell}\n"
        "========================================\n"
        f"  AGENT BLOCKED - human needed\n"
        f"  [{record['category']}] {record['title']}\n"
        f"  id: {record['id']}\n"
        f"  open the inbox to unblock it\n"
        "========================================",
        file=sys.stderr,
        flush=True,
    )

    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    try:
        httpx.post(
            f"https://ntfy.sh/{topic}",
            content=f"[{record['category']}] {record['title']} ({record['id']})",
            headers={"Title": "Agent blocked - human needed", "Priority": "high"},
            timeout=5.0,
        )
    except Exception as exc:  # noqa: BLE001 - notifications are best-effort
        print(f"(ntfy notify failed, ignoring: {exc})", file=sys.stderr)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.post("/requests")
def create_request(body: CreateRequest) -> dict[str, str]:
    """Create an escalation request and alert a human. Returns id + status."""
    try:
        schema = normalize_schema(body.response_schema)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    record = db.create_request(
        title=body.title,
        context=body.context,
        instructions=body.instructions,
        response_schema=schema,
        category=body.category,
    )
    _notify(record)
    return {"id": record["id"], "status": record["status"]}


@app.get("/requests/{req_id}")
def get_request(req_id: str) -> dict[str, Any]:
    """Full record for a single request. This is what the agent long-polls."""
    record = db.get_request(req_id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown request id")
    return record


@app.get("/api/requests")
def list_requests(status: Optional[str] = None) -> dict[str, Any]:
    """List requests for the inbox, optionally filtered by status."""
    return {"requests": db.list_requests(status)}


@app.post("/requests/{req_id}/resolve")
def resolve_request(req_id: str, body: ResolveRequest) -> dict[str, Any]:
    """Submit the human's values, validating them against the stored schema.

    404 on unknown or already-resolved ids; 400 if a required field is
    missing. On success the record flips to resolved and the agent's next
    poll picks up the response.
    """
    record = db.get_request(req_id)
    if record is None or record["status"] != "pending":
        raise HTTPException(
            status_code=404, detail="unknown or already-resolved request id"
        )

    try:
        cleaned = validate_response(record["response_schema"], body.response)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    updated = db.resolve_request(req_id, cleaned)
    if updated is None:
        # Lost a race: someone resolved it between our check and write.
        raise HTTPException(
            status_code=404, detail="unknown or already-resolved request id"
        )
    return updated


@app.get("/api/stats")
def get_stats() -> dict[str, Any]:
    """Counts by category and status plus average resolve time."""
    return db.stats()


@app.get("/")
def index() -> FileResponse:
    """Serve the inbox single-page app."""
    return FileResponse(STATIC_DIR / "index.html")
