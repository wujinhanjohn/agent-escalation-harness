"""Self-running demo agent that drives the escalation loop over HTTP.

No Claude Code wiring required: this simulates an agent building a todo app
that repeatedly hits walls only a human can clear. It creates each request,
blocks while polling, and on resolve prints the .env lines it "would write",
then moves on. Run three walls so /api/stats shows category variety.

Usage:
    python demo/demo_agent.py
Point at a non-default backend with HARNESS_URL.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx

HARNESS_URL = os.environ.get("HARNESS_URL", "http://127.0.0.1:8000").rstrip("/")
POLL_INTERVAL_SECONDS = 2.0
TIMEOUT_SECONDS = 600

# ANSI styling for a readable live demo.
DIM = "\033[2m"
BOLD = "\033[1m"
AMBER = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
RESET = "\033[0m"


def say(text: str = "", color: str = "") -> None:
    print(f"{color}{text}{RESET}" if color else text, flush=True)


def think(text: str) -> None:
    say(f"  {DIM}agent> {text}{RESET}")


def type_out(text: str) -> None:
    """Narrate a line with a small delay so the demo reads like a story."""
    say(f"{BOLD}{text}{RESET}")
    time.sleep(0.6)


WALLS: list[dict[str, Any]] = [
    {
        "story": "Wiring up auth. I need a Postgres database and API keys, but "
        "I cannot create a Supabase project myself.",
        "title": "Create Supabase project",
        "context": "Building auth for the todo app. Needs Postgres + keys.",
        "instructions": (
            "1. Create a new project at supabase.com\n"
            "2. Open Project Settings -> API\n"
            "3. Paste the URL and the two keys below"
        ),
        "category": "provisioning",
        "response_schema": [
            {"name": "SUPABASE_URL", "type": "string", "secret": False, "required": True},
            {"name": "SUPABASE_ANON_KEY", "type": "string", "secret": False, "required": True},
            {"name": "SUPABASE_SERVICE_KEY", "type": "secret", "secret": True, "required": True},
        ],
    },
    {
        "story": "Todo reminders need email. I have to sign up for an email API "
        "and grab a key - that needs a human with the account.",
        "title": "Get Resend API key",
        "context": "Sending reminder emails from the todo app.",
        "instructions": (
            "1. Sign in at resend.com\n"
            "2. Create an API key (full access)\n"
            "3. Paste it below"
        ),
        "category": "api-key",
        "response_schema": [
            {"name": "RESEND_API_KEY", "type": "secret", "secret": True, "required": True},
        ],
    },
    {
        "story": "Going to production. I need a real domain pointed at the app, "
        "which means registering one - not something I can do alone.",
        "title": "Register production domain",
        "context": "Deploying the todo app; need a domain + DNS target.",
        "instructions": (
            "1. Register a domain at your registrar\n"
            "2. Add an A/ALIAS record to the deploy target\n"
            "3. Paste the domain and target below"
        ),
        "category": "domain",
        "response_schema": [
            {"name": "APP_DOMAIN", "type": "string", "secret": False, "required": True},
            {"name": "DNS_TARGET", "type": "string", "secret": False, "required": True},
        ],
    },
]


def run_wall(client: httpx.Client, wall: dict[str, Any]) -> None:
    type_out(f"\n>> {wall['story']}")
    think(f"raising an escalation [{wall['category']}]: {wall['title']}")

    created = client.post(
        "/requests",
        json={
            "title": wall["title"],
            "context": wall["context"],
            "instructions": wall["instructions"],
            "response_schema": wall["response_schema"],
            "category": wall["category"],
        },
    )
    created.raise_for_status()
    req_id = created.json()["id"]
    say(f"  {AMBER}[BLOCKED]{RESET} request {BOLD}{req_id}{RESET} is waiting for a human...")
    say(f"  {DIM}open the inbox and fill the form to unblock me{RESET}")

    deadline = time.monotonic() + TIMEOUT_SECONDS
    spinner = "|/-\\"
    i = 0
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        rec = client.get(f"/requests/{req_id}").json()
        if rec["status"] == "resolved":
            say(f"\r  {GREEN}[UNBLOCKED]{RESET} human responded. Resuming.        ")
            values = rec["response"]
            say(f"  {DIM}received {len(values)} value(s). Writing .env:{RESET}")
            for k, v in values.items():
                field = next(
                    (f for f in wall["response_schema"] if f["name"] == k), {}
                )
                shown = "********" if field.get("secret") else v
                say(f"    {CYAN}{k}{RESET}={shown}")
            think("values written. Continuing the build.\n")
            return
        sys.stdout.write(
            f"\r  {DIM}polling {req_id} {spinner[i % 4]} still blocked{RESET}"
        )
        sys.stdout.flush()
        i += 1

    say(f"\r  {AMBER}[TIMEOUT]{RESET} no human yet; would keep working and check back later.")


def main() -> None:
    say(f"{BOLD}=== Demo agent: building a todo app ==={RESET}")
    say(f"{DIM}backend: {HARNESS_URL}{RESET}")
    try:
        with httpx.Client(base_url=HARNESS_URL, timeout=15.0) as client:
            # Fail fast with a friendly message if the backend is not up.
            try:
                client.get("/api/stats").raise_for_status()
            except Exception:
                say(
                    f"{AMBER}Could not reach the backend at {HARNESS_URL}.{RESET}\n"
                    "Start it first:  ./run.sh   (or see the README)"
                )
                sys.exit(1)

            for wall in WALLS:
                run_wall(client, wall)

            say(f"{BOLD}=== All walls cleared. Todo app is unblocked. ==={RESET}")
            stats = client.get("/api/stats").json()
            say(
                f"{DIM}stats: {stats['resolved']} resolved across "
                f"{len(stats['by_category'])} categories; "
                f"avg resolve {stats['avg_resolve_seconds']}s{RESET}"
            )
    except KeyboardInterrupt:
        say("\ninterrupted.")


if __name__ == "__main__":
    main()
