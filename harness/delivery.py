"""Secret-by-reference delivery of resolved values to the agent.

The core rule: an agent must never receive a secret's raw bytes, because its
tool results land in the model's context and the conversation transcript.
Instead, secret fields are written straight to a ``.env`` file on the machine
and the agent gets back only a reference note (the variable name), so it can
write code like ``os.environ["STRIPE_SECRET_KEY"]`` without ever seeing the
value. Non-secret fields pass through normally.

These functions are deliberately free of any MCP/HTTP concerns so they can be
unit-tested directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def classify_fields(
    schema: list[dict[str, Any]], response: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a resolved response into ``(public, secret)`` by the schema flag."""
    secret_names = {f["name"] for f in schema if f.get("secret")}
    public: dict[str, Any] = {}
    secret: dict[str, Any] = {}
    for name, value in (response or {}).items():
        (secret if name in secret_names else public)[name] = value
    return public, secret


def _quote(value: Any) -> str:
    """Render a value for a .env line, quoting only when needed."""
    s = str(value)
    if s == "" or any(c in s for c in ' \t"\'#\n\\'):
        s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{s}"'
    return s


def write_env(env_path: str, values: dict[str, Any]) -> list[str]:
    """Upsert ``KEY=value`` pairs into a .env file, preserving other lines.

    An existing key is updated in place; a new key is appended. A newly
    created file is chmod 0600 because it now holds secrets. Returns the list
    of key names written.
    """
    path = Path(env_path)
    is_new = not path.exists()
    lines = path.read_text().splitlines() if not is_new else []

    # Map existing KEY -> line index so we can update in place.
    index: dict[str, int] = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        index[key] = i

    written: list[str] = []
    for key, value in values.items():
        entry = f"{key}={_quote(value)}"
        if key in index:
            lines[index[key]] = entry
        else:
            lines.append(entry)
        written.append(key)

    path.write_text("\n".join(lines) + "\n")
    if is_new:
        os.chmod(path, 0o600)
    return written


def build_agent_response(
    schema: list[dict[str, Any]],
    response: dict[str, Any] | None,
    env_path: str,
) -> tuple[dict[str, Any], list[str]]:
    """Build the agent-facing view of a resolved response.

    Public fields pass through. Secret fields are written to ``env_path`` and
    replaced with a reference note so the raw value never reaches the agent.
    Returns ``(agent_view, secrets_written)``.
    """
    public, secret = classify_fields(schema, response)
    agent_view: dict[str, Any] = dict(public)
    written: list[str] = []
    if secret:
        written = write_env(env_path, secret)
        for name in secret:
            agent_view[name] = (
                f"<written to {env_path}; reference as ${{{name}}}, "
                "do not print or echo it>"
            )
    return agent_view, written
