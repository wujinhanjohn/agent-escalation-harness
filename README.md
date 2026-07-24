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
        "HARNESS_URL": "http://127.0.0.1:8000",
        "HARNESS_ENV_PATH": "/absolute/path/to/your/project/.env"
      }
    }
  }
}
```

`HARNESS_ENV_PATH` points at the `.env` you want resolved secrets written to (defaults to `.env` in the process's working directory). Set it to your project's `.env` so keys land where your app reads them. See [Security](#security) for how secrets are handled and how to set an encryption key.

The agent now has two tools:

- `request_human(title, instructions, context, response_schema, category, timeout_seconds=300)` - files a request and blocks (long-poll) until a human resolves it or the timeout hits. On resolve, non-secret values come back inline and secret fields are written straight to `.env` (see [Security](#security)); on timeout it returns `{status: "pending", request_id}` so the agent can keep working and check back.
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

## Security

Secrets get two protections, addressing two different exposures.

**Secrets by reference - keeping keys out of the agent's context.** An agent's tool results land in the model's context window and the conversation transcript, so returning a raw API key there would leak it. Instead, when a request resolves, fields marked `secret: true` are written directly to a `.env` file on the machine, and the agent gets back only a reference note (the variable name), never the value:

```json
{
  "SUPABASE_URL": "https://abc.supabase.co",
  "SUPABASE_SERVICE_KEY": "<written to .env; reference as ${SUPABASE_SERVICE_KEY}, do not print or echo it>",
  "secrets_written_to_env": ["SUPABASE_SERVICE_KEY"]
}
```

The agent references the secret by name (`os.environ["SUPABASE_SERVICE_KEY"]`) and its raw bytes never enter the model. Non-secret fields pass through inline. Target file via `HARNESS_ENV_PATH` (default `.env`, created `0600`).

**Encryption at rest - protecting the database file.** The human's `response` is the only column that can hold secrets, so it is encrypted (Fernet: AES-128-CBC + HMAC) before it touches SQLite. A stolen, backed-up, or accidentally committed `harness.db` is useless without the key. The key is resolved from `HARNESS_SECRET_KEY` (base64 Fernet key in the env, e.g. sourced from an OS keychain) or a `HARNESS_KEY_FILE` (default `.harness_key`, auto-created `0600` on first run so it works with zero config). Both `.env` and `.harness_key` are gitignored.

To pin your own key instead of the auto-generated file, set it before starting the backend:

```bash
export HARNESS_SECRET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

Honest caveat: nothing stops an agent from *explicitly* running `cat .env` as a separate action - no local tool can fully prevent that. What this guarantees is that the normal resolve flow never places a secret in the model's context, and the values never sit in plaintext on disk.

## Design decisions

- **Polling, not a blocking backend call.** The agent long-polls `GET /requests/{id}` and the backend resolve is a fast, stateless write. Nothing is held open server-side, so a slow human or a dropped connection can't wedge a request, the timeout path is trivial (return `pending`, keep working), and the exact same endpoint feeds the browser inbox. A blocking call would couple request lifetime to a single held HTTP connection and make the "give up and check back later" story much harder.
- **Schema-driven forms.** The request declares the fields it needs; the inbox renders inputs from that schema and the backend validates against it. One source of truth means the form can never drift from what the agent expects, secret-masking is declarative (`secret: true`), and adding a new kind of wall needs zero UI code.
- **Category as instrumentation.** Every wall is tagged with a `category`, and `/api/stats` aggregates by it. Over time that answers "which wall do I hit most" - the questions that tell you what to actually automate away next. The stats view is the point, not decoration.
