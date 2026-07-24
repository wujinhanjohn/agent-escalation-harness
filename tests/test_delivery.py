"""Tests for secret-by-reference delivery (harness/delivery.py)."""

from pathlib import Path

from harness.delivery import build_agent_response, classify_fields, write_env

SCHEMA = [
    {"name": "SUPABASE_URL", "secret": False, "required": True},
    {"name": "SUPABASE_SERVICE_KEY", "secret": True, "required": True},
]


def test_classify_splits_public_and_secret():
    public, secret = classify_fields(
        SCHEMA,
        {"SUPABASE_URL": "https://x.co", "SUPABASE_SERVICE_KEY": "svc_secret"},
    )
    assert public == {"SUPABASE_URL": "https://x.co"}
    assert secret == {"SUPABASE_SERVICE_KEY": "svc_secret"}


def test_secret_never_appears_in_agent_view(tmp_path):
    env = str(tmp_path / ".env")
    agent_view, written = build_agent_response(
        SCHEMA,
        {"SUPABASE_URL": "https://x.co", "SUPABASE_SERVICE_KEY": "svc_secret"},
        env,
    )
    # Public value passes through; secret value does NOT.
    assert agent_view["SUPABASE_URL"] == "https://x.co"
    assert "svc_secret" not in agent_view["SUPABASE_SERVICE_KEY"]
    assert "reference as ${SUPABASE_SERVICE_KEY}" in agent_view["SUPABASE_SERVICE_KEY"]
    assert written == ["SUPABASE_SERVICE_KEY"]
    # And the raw secret is nowhere in the returned structure.
    assert "svc_secret" not in repr(agent_view)


def test_secret_is_written_to_env(tmp_path):
    env = tmp_path / ".env"
    build_agent_response(
        SCHEMA,
        {"SUPABASE_URL": "https://x.co", "SUPABASE_SERVICE_KEY": "svc_secret"},
        str(env),
    )
    contents = env.read_text()
    assert "SUPABASE_SERVICE_KEY=svc_secret" in contents
    # Non-secret fields are not written to .env by this path.
    assert "SUPABASE_URL" not in contents
    # New secret file is chmod 0600.
    assert oct(env.stat().st_mode)[-3:] == "600"


def test_write_env_upserts_and_preserves(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EXISTING=keep\nSUPABASE_SERVICE_KEY=old\n")
    write_env(str(env), {"SUPABASE_SERVICE_KEY": "new", "NEW_KEY": "added"})
    lines = env.read_text().splitlines()
    assert "EXISTING=keep" in lines
    assert "SUPABASE_SERVICE_KEY=new" in lines
    assert "SUPABASE_SERVICE_KEY=old" not in lines
    assert "NEW_KEY=added" in lines


def test_write_env_quotes_values_with_spaces(tmp_path):
    env = tmp_path / ".env"
    write_env(str(env), {"K": "a b#c"})
    assert 'K="a b#c"' in env.read_text()


def test_no_secrets_means_empty_env(tmp_path):
    env = tmp_path / ".env"
    agent_view, written = build_agent_response(
        [{"name": "PLAIN", "secret": False, "required": True}],
        {"PLAIN": "value"},
        str(env),
    )
    assert agent_view == {"PLAIN": "value"}
    assert written == []
    assert not env.exists()
