# Agent Escalation Harness

**Pause on a wall, ask a human, resume.** A local, self-contained harness that lets an AI coding agent stop when it hits something only a human can do, request the one thing as a typed form, get the answer back as structured data, and continue - no cloud accounts, no external services.

Three small pieces share one SQLite database: a FastAPI backend, an MCP server any agent can call, and a browser inbox where a human clears the wall. It runs entirely on your machine.

## The wall problem

Coding agents stall on the handful of steps they cannot do alone: provisioning a Supabase project, minting a Stripe key, registering a domain.
This harness turns that dead stop into a structured escalation: the agent files a typed request, a human fills a generated form, and the agent resumes with the values dropped straight into `.env` - all on your machine, no cloud accounts, no external services.

## Architecture

```
                       one shared SQLite DB (requests table)
                                     |
        +----------------------------+----------------------------+
        |                            |                            |
  MCP server (stdio)          FastAPI backend               Inbox (browser)
  mcp_server.py               harness/app.py                served at /
  - request_human   --POST--> POST /requests                - polls /api/requests
  - check_request   <-poll--  GET  /requests/{id}            - schema-driven form
                              POST /requests/{id}/resolve <--- "Send to agent"
                              GET  /api/stats  (by category)
        ^                            ^
        |                            |
   real Claude Code            demo/demo_agent.py
   session                     (self-running demo, no Claude needed)
```

- **Backend + inbox** - one FastAPI process. Owns the SQLite table and serves the inbox page.
- **MCP server** - FastMCP over stdio. Exposes `request_human` and `check_request` to any agent.
- **Demo agent** - drives the whole loop over plain HTTP so you can demo it live without wiring up Claude Code.

## Quickstart

```bash
# 1. install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. start the backend + inbox (terminal 1)
./run.sh
# -> serving on http://127.0.0.1:8000

# 3. open the inbox
open http://127.0.0.1:8000

# 4. run the demo agent (terminal 2)
source .venv/bin/activate
python demo/demo_agent.py
```

The demo agent narrates building a todo app, hits three walls in sequence (provisioning, then an API key, then a domain), and blocks on each.
Fill the form in the inbox, click **Send to agent**, and watch that terminal resume with the values it "received" and the `.env` lines it would write.
Every wall is logged and counted at `/api/stats`.

### Run the tests

```bash
pytest
```

## Wire up a real Claude Code agent

Register the MCP server so a live Claude Code session can escalate through the same backend.
Start the backend first (`./run.sh`), then add this to your Claude Code MCP config (`~/.claude.json`, or `.mcp.json` in a project):

```json
{
  "mcpServers": {
    "escalation-harness": {
      "command": "/absolute/path/to/harness/.venv/bin/python",
      "args": ["/absolute/path/to/harness/mcp_server.py"],
      "env": {
        "HARNESS_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

The agent now has two tools:

- `request_human(title, instructions, context, response_schema, category, timeout_seconds=300)` - files a request and blocks (long-poll) until a human resolves it or the timeout hits. On resolve it returns the human's values; on timeout it returns `{status: "pending", request_id}` so the agent can keep working and check back.
- `check_request(request_id)` - non-blocking status/response lookup for a pending request.

Optional: set `NTFY_TOPIC` in the backend's env to also get a phone push via [ntfy.sh](https://ntfy.sh) when a wall is raised. A failed push never breaks request creation.

## Data model

A request is the core abstraction. The `response_schema` both **generates the inbox form** and **validates** what the human submits.

```json
{
  "id": "req_a1b2",
  "title": "Create Supabase project",
  "context": "Building auth for the todo app. Needs Postgres + keys.",
  "instructions": "1. New project at supabase.com  2. Paste the values below",
  "response_schema": [
    {"name": "SUPABASE_URL",         "type": "string", "secret": false, "required": true},
    {"name": "SUPABASE_ANON_KEY",    "type": "string", "secret": false, "required": true},
    {"name": "SUPABASE_SERVICE_KEY", "type": "secret", "secret": true,  "required": true}
  ],
  "category": "provisioning",
  "status": "pending",
  "response": null,
  "created_at": "2026-07-21T04:06:00Z",
  "resolved_at": null
}
```

Secret fields render as password inputs. `category` tags every wall so `/api/stats` can aggregate them.

## Design decisions

- **Polling, not a blocking backend call.** The agent long-polls `GET /requests/{id}` and the backend resolve is a fast, stateless write. Nothing is held open server-side, so a slow human or a dropped connection can't wedge a request, the timeout path is trivial (return `pending`, keep working), and the exact same endpoint feeds the browser inbox. A blocking call would couple request lifetime to a single held HTTP connection and make the "give up and check back later" story much harder.
- **Schema-driven forms.** The request declares the fields it needs; the inbox renders inputs from that schema and the backend validates against it. One source of truth means the form can never drift from what the agent expects, secret-masking is declarative (`secret: true`), and adding a new kind of wall needs zero UI code.
- **Category as instrumentation.** Every wall is tagged with a `category`, and `/api/stats` aggregates by it. Over time that answers "which wall do I hit most" - the questions that tell you what to actually automate away next. The stats view is the point, not decoration.

## Interview talking points

- **Human-in-the-loop as a typed protocol.** The interesting part isn't the form; it's treating "ask a human" as a structured request/response with a schema, validation, and a status lifecycle - the same shape as any other tool call.
- **Same server, two clients.** A real Claude Code agent (via MCP) and a scripted demo agent (via raw HTTP) drive an identical backend. The MCP layer is a thin adapter over the HTTP API, which keeps the core testable without an agent in the loop.
- **Failure modes are designed, not incidental.** Timeouts return `pending` instead of erroring; notifications are best-effort and never block creation; resolve is idempotent-safe (already-resolved -> 404) and validates required fields before accepting.
- **Instrumentation from day one.** Tagging every escalation by category turns the harness into a dataset about where the agent gets stuck, which is the real payoff of building the abstraction.
- **Deliberately small.** Stdlib SQLite, no ORM, vanilla-JS inbox, pinned minimal deps. Every piece is legible in one sitting.
```
