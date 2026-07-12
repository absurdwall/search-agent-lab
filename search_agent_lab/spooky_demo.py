"""Small REST helpers for Spooky's shared teaching server."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
import secrets
from typing import Any
from urllib import error, parse, request


BASE_URL = "http://127.0.0.1:8000"
ADK_WEB_URL = BASE_URL
APP_NAME = "spooky"
USER_ID = "user"
STARTUP_COMMAND = """source .venv/bin/activate

adk api_server \\
  --with_ui \\
  --session_service_uri=memory:// \\
  --no-reload \\
  --port 8000 \\
  ."""

_KNOWN_TOOLS = {"search_glossary", "get_glossary_terms"}
_SAFE_ERROR_CODE = re.compile(r"^[A-Z0-9_-]{1,80}$")


def _json_request(
    method: str, path: str, payload: dict[str, object] | None = None
) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    http_request = request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method=method
    )
    with request.urlopen(http_request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def check_server() -> None:
    """Confirm that the shared ADK server is healthy and exposes Spooky."""
    try:
        health = _json_request("GET", "/health")
        apps = _json_request("GET", "/list-apps")
        if health != {"status": "ok"} or not isinstance(apps, list):
            raise ValueError("unexpected ADK server response")
        if APP_NAME not in apps:
            raise ValueError("Spooky is not loaded")
    except (error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Spooky server is not ready. Start it from the repository "
            f"root with:\n\n{STARTUP_COMMAND}"
        ) from exc


def create_session() -> dict[str, object]:
    """Create a fresh in-memory Spooky session for the ADK Web user."""
    session_id = f"spooky-demo-{secrets.token_hex(3)}"
    result = _json_request(
        "POST",
        f"/apps/{APP_NAME}/users/{USER_ID}/sessions",
        {"sessionId": session_id},
    )
    if not isinstance(result, dict):
        raise RuntimeError("ADK did not return a session object.")
    return result


def run_message(session_id: str, message: str) -> list[dict[str, object]]:
    """Submit one real message to the shared ADK server through POST /run."""
    result = _json_request(
        "POST",
        "/run",
        {
            "appName": APP_NAME,
            "userId": USER_ID,
            "sessionId": session_id,
            "newMessage": {"role": "user", "parts": [{"text": message}]},
        },
    )
    if not isinstance(result, list) or not all(
        isinstance(event, dict) for event in result
    ):
        raise RuntimeError("ADK did not return an event list.")
    return result


def get_session(session_id: str) -> dict[str, object]:
    """Fetch the same session that was used for a Spooky run."""
    safe_session_id = parse.quote(session_id, safe="")
    result = _json_request(
        "GET",
        f"/apps/{APP_NAME}/users/{USER_ID}/sessions/{safe_session_id}",
    )
    if not isinstance(result, dict):
        raise RuntimeError("ADK did not return a session object.")
    return result


def _event_identity(event: Mapping[str, object]) -> dict[str, str]:
    identity: dict[str, str] = {}
    if isinstance(event.get("id"), str):
        identity["event_id"] = event["id"]
    if isinstance(event.get("invocationId"), str):
        identity["invocation_id"] = event["invocationId"]
    return identity


def _safe_arguments(name: str, value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    if name == "search_glossary" and isinstance(value.get("query"), str):
        return {"query": value["query"]}
    if name == "get_glossary_terms" and isinstance(value.get("term_ids"), list):
        return {
            "term_ids": [item for item in value["term_ids"] if isinstance(item, str)]
        }
    return {}


def _safe_match(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, object] = {}
    if value.get("kind") in {"exact", "name", "content"}:
        safe["kind"] = value["kind"]
    if isinstance(value.get("fields"), list):
        safe["fields"] = [item for item in value["fields"] if isinstance(item, str)]
    return safe


def _safe_search_result(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, object] = {}
    if value.get("status") in {"ok", "not_found"}:
        safe["status"] = value["status"]
    if isinstance(value.get("query"), str):
        safe["query"] = value["query"]
    if isinstance(value.get("results"), list):
        results: list[dict[str, object]] = []
        for item in value["results"]:
            if not isinstance(item, Mapping):
                continue
            result = {
                key: item[key]
                for key in ("id", "term", "simple_definition")
                if isinstance(item.get(key), str)
            }
            result["match"] = _safe_match(item.get("match"))
            results.append(result)
        safe["results"] = results
    return safe


def _safe_term(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, object] = {
        key: value[key]
        for key in (
            "id",
            "term",
            "category",
            "status",
            "introduced_in",
            "last_reviewed",
            "canonical_url",
        )
        if isinstance(value.get(key), str)
    }
    if isinstance(value.get("aliases"), list):
        safe["aliases"] = [item for item in value["aliases"] if isinstance(item, str)]
    if isinstance(value.get("sections"), Mapping):
        safe["sections"] = {
            key: item for key, item in value["sections"].items() if isinstance(key, str) and isinstance(item, str)
        }
    if isinstance(value.get("relations"), list):
        safe["relations"] = [
            {key: item[key] for key in ("type", "target") if isinstance(item.get(key), str)}
            for item in value["relations"]
            if isinstance(item, Mapping)
        ]
    if isinstance(value.get("sources"), list):
        safe["sources"] = [
            {key: item[key] for key in ("title", "url", "note") if isinstance(item.get(key), str)}
            for item in value["sources"]
            if isinstance(item, Mapping)
        ]
    return safe


def _safe_terms_result(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, object] = {}
    if value.get("status") in {"ok", "partial", "not_found"}:
        safe["status"] = value["status"]
    if isinstance(value.get("terms"), list):
        safe["terms"] = [_safe_term(term) for term in value["terms"]]
    if isinstance(value.get("missing_ids"), list):
        safe["missing_ids"] = [
            item for item in value["missing_ids"] if isinstance(item, str)
        ]
    return safe


def _safe_response(name: str, value: object) -> dict[str, object]:
    if name == "search_glossary":
        return _safe_search_result(value)
    if name == "get_glossary_terms":
        return _safe_terms_result(value)
    return {}


def summarize_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    """Reduce real ADK JSON events to a small, public, allowlisted timeline."""
    timeline: list[dict[str, object]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        identity = _event_identity(event)
        error_code = event.get("errorCode")
        if isinstance(error_code, str):
            code = error_code if _SAFE_ERROR_CODE.fullmatch(error_code) else "ADK_ERROR"
            timeline.append(
                {
                    "type": "error",
                    "code": code,
                    "message": "ADK reported an error; details are omitted.",
                    **identity,
                }
            )

        content = event.get("content")
        parts = content.get("parts") if isinstance(content, Mapping) else None
        if not isinstance(parts, list):
            continue
        has_tool_part = any(
            isinstance(part, Mapping)
            and ("functionCall" in part or "functionResponse" in part)
            for part in parts
        )
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            call = part.get("functionCall")
            if isinstance(call, Mapping) and call.get("name") in _KNOWN_TOOLS:
                name = str(call["name"])
                timeline.append(
                    {
                        "type": "function_call",
                        "name": name,
                        "arguments": _safe_arguments(name, call.get("args")),
                        **identity,
                    }
                )
            response = part.get("functionResponse")
            if isinstance(response, Mapping) and response.get("name") in _KNOWN_TOOLS:
                name = str(response["name"])
                timeline.append(
                    {
                        "type": "function_response",
                        "name": name,
                        "result": _safe_response(name, response.get("response")),
                        **identity,
                    }
                )
            text = part.get("text")
            if (
                isinstance(text, str)
                and text
                and part.get("thought") is not True
                and not has_tool_part
                and event.get("partial") is not True
                and event.get("author") != "user"
            ):
                timeline.append({"type": "final_text", "text": text, **identity})
    return timeline
