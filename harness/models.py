"""Request data shapes and response-schema validation.

A request's ``response_schema`` is the core abstraction: a list of field
descriptors that both drives the inbox form and validates what the human
submits back. Keeping the validation here (not in the HTTP layer) means the
rules are shared by the endpoint and the tests and stay easy to reason about.
"""

from __future__ import annotations

from typing import Any


VALID_STATUSES = ("pending", "resolved")


def normalize_schema(schema: Any) -> list[dict[str, Any]]:
    """Coerce a raw response_schema into a clean list of field descriptors.

    Each field ends up with the keys ``name``, ``type``, ``secret`` and
    ``required``. Missing optional keys are defaulted so the inbox and
    validator never have to guess. Raises ValueError on anything malformed so
    a bad request is rejected at creation time rather than at resolve time.
    """
    if not isinstance(schema, list) or not schema:
        raise ValueError("response_schema must be a non-empty list")

    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in schema:
        if not isinstance(raw, dict):
            raise ValueError("each response_schema field must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("each field needs a non-empty string 'name'")
        if name in seen:
            raise ValueError(f"duplicate field name: {name}")
        seen.add(name)
        secret = bool(raw.get("secret", False))
        fields.append(
            {
                "name": name,
                # A field is either a plain "string" or a "secret". We keep an
                # explicit type for display while `secret` stays the source of
                # truth for password-masking.
                "type": raw.get("type", "secret" if secret else "string"),
                "secret": secret,
                "required": bool(raw.get("required", True)),
            }
        )
    return fields


def validate_response(
    schema: list[dict[str, Any]], response: Any
) -> dict[str, Any]:
    """Validate a human's submitted values against the request schema.

    Returns the response trimmed to the schema's fields. Raises ValueError if
    it is not an object or if any ``required`` field is missing or blank.
    """
    if not isinstance(response, dict):
        raise ValueError("response must be an object of field name -> value")

    cleaned: dict[str, Any] = {}
    missing: list[str] = []
    for field in schema:
        name = field["name"]
        value = response.get(name)
        if field["required"] and (value is None or value == ""):
            missing.append(name)
            continue
        if name in response:
            cleaned[name] = value

    if missing:
        raise ValueError("missing required field(s): " + ", ".join(missing))
    return cleaned
