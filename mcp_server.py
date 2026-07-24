"""MCP server (FastMCP, stdio) exposing the escalation harness to any agent.

Two tools:
  request_human  - raise a wall, block on it (long-poll), return human values
  check_request  - one-shot status/response lookup for a known request id

The backend URL comes from HARNESS_URL (default http://127.0.0.1:8000). Run
this over stdio and register it with a Claude Code MCP config (see README).
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# Claude Code launches this script from the user's project directory, not from
# the harness repo, so make the bundled `harness` package importable by adding
# this file's directory to the path regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness.delivery import build_agent_response  # noqa: E402

HARNESS_URL = os.environ.get("HARNESS_URL", "http://127.0.0.1:8000").rstrip("/")
# Where secret fields are written so they never enter the agent's context.
HARNESS_ENV_PATH = os.environ.get("HARNESS_ENV_PATH", ".env")
POLL_INTERVAL_SECONDS = 2.0

mcp = FastMCP("agent-escalation-harness")


@mcp.tool()
def request_human(
    title: str,
    instructions: str,
    context: str = "",
    response_schema: list[dict[str, Any]] | None = None,
    category: str = "general",
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Pause and ask a human to do the one thing you can't, then resume.

    Use this when you hit a wall that needs a human: provisioning a Supabase
    project, generating a Stripe key, registering a domain. Describe the wall
    and declare the values you need back via ``response_schema``.

    Args:
        title: Short label for the wall, e.g. "Create Supabase project".
        instructions: Numbered steps telling the human exactly what to do.
        context: Why you need this, so the human has the full picture.
        response_schema: List of fields you need back. Each is
            ``{"name", "type", "secret", "required"}``. Secret fields are
            masked in the inbox. Example:
            ``[{"name": "SUPABASE_URL", "secret": false, "required": true}]``.
        category: Wall type for instrumentation, e.g. "provisioning",
            "api-key", "domain". Aggregated in /api/stats.
        timeout_seconds: How long to block waiting for the human.

    Returns:
        On resolve: ``{"status": "resolved", "request_id", "response",
        "secrets_written_to_env", "env_path"}``. Non-secret fields appear in
        ``response`` with their values. Secret fields (``secret: true``) are
        written directly to the .env file and appear in ``response`` only as a
        reference note, never as the raw value - their names are listed in
        ``secrets_written_to_env``. Reference them by name (e.g.
        ``os.environ["STRIPE_SECRET_KEY"]``); do not print or echo them. On
        timeout: ``{"status": "pending", "request_id"}`` so you can keep
        working and call ``check_request`` later.
    """
    if response_schema is None:
        response_schema = [{"name": "value", "secret": False, "required": True}]

    with httpx.Client(base_url=HARNESS_URL, timeout=10.0) as client:
        created = client.post(
            "/requests",
            json={
                "title": title,
                "instructions": instructions,
                "context": context,
                "response_schema": response_schema,
                "category": category,
            },
        )
        created.raise_for_status()
        req_id = created.json()["id"]

        # Long-poll until the human resolves it or we run out of patience.
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_SECONDS)
            rec = client.get(f"/requests/{req_id}").json()
            if rec["status"] == "resolved":
                agent_view, written = build_agent_response(
                    rec["response_schema"], rec["response"], HARNESS_ENV_PATH
                )
                return {
                    "status": "resolved",
                    "request_id": req_id,
                    "response": agent_view,
                    "secrets_written_to_env": written,
                    "env_path": HARNESS_ENV_PATH if written else None,
                }

    # Still pending: hand the id back so the agent can keep working.
    return {"status": "pending", "request_id": req_id}


@mcp.tool()
def check_request(request_id: str) -> dict[str, Any]:
    """Check a previously raised wall without blocking.

    Use this to poll a request that ``request_human`` returned as still
    pending after its timeout.

    Args:
        request_id: The id returned by ``request_human``.

    Returns:
        ``{"status", "request_id", "response"}``. ``response`` is null while
        still pending. Once resolved it follows the same secret-by-reference
        rule as ``request_human``: non-secret values are present, secret
        fields are written to .env and shown only as a reference note (their
        names in ``secrets_written_to_env``). ``status`` is "unknown" if the
        id does not exist.
    """
    with httpx.Client(base_url=HARNESS_URL, timeout=10.0) as client:
        res = client.get(f"/requests/{request_id}")
        if res.status_code == 404:
            return {"status": "unknown", "request_id": request_id, "response": None}
        res.raise_for_status()
        rec = res.json()

    if rec["status"] != "resolved":
        return {"status": rec["status"], "request_id": request_id, "response": None}

    agent_view, written = build_agent_response(
        rec["response_schema"], rec["response"], HARNESS_ENV_PATH
    )
    return {
        "status": "resolved",
        "request_id": request_id,
        "response": agent_view,
        "secrets_written_to_env": written,
    }


if __name__ == "__main__":
    mcp.run()
