"""Convert raw ADK events into a small allowlisted public timeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google.adk.events import Event


TimelineRow = tuple[str, object]
FINAL_ANSWER_ACKNOWLEDGEMENT = (
    "Final response received (content omitted by setup check)."
)
REDACTED_RUNTIME_ERROR = "redacted ADK error"


def allowlisted_evidence(
    field: str,
    value: object,
    expected_evidence: Mapping[str, object],
) -> str:
    """Return one exact public value or a fixed redaction marker."""
    expected = expected_evidence.get(field)
    return expected if isinstance(expected, str) and value == expected else "redacted"


def redact_tool_call(
    call: object,
    expected_evidence: Mapping[str, object],
) -> dict[str, object]:
    expected_tool = expected_evidence.get("tool")
    if (
        not isinstance(expected_tool, str)
        or getattr(call, "name", None) != expected_tool
    ):
        return {"redacted": True}
    arguments = getattr(call, "args", None)
    topic = arguments.get("topic") if isinstance(arguments, Mapping) else None
    return {
        "tool": expected_tool,
        "arguments": {
            "topic": allowlisted_evidence(
                "topic",
                topic,
                expected_evidence,
            )
        },
    }


def redact_tool_result(
    response: object,
    expected_evidence: Mapping[str, object],
) -> dict[str, object]:
    expected_tool = expected_evidence.get("tool")
    if (
        not isinstance(expected_tool, str)
        or getattr(response, "name", None) != expected_tool
    ):
        return {"redacted": True}
    raw_result = getattr(response, "response", None)
    if not isinstance(raw_result, Mapping):
        return {"tool": expected_tool, "result": {"status": "redacted"}}
    return {
        "tool": expected_tool,
        "result": {
            field: allowlisted_evidence(
                field,
                raw_result.get(field),
                expected_evidence,
            )
            for field in ("status", "topic", "summary")
        },
    }


def has_nonthought_final_text(event: Event) -> bool:
    """Recognize final public text without returning its content."""
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return any(
        getattr(part, "text", None) and not getattr(part, "thought", False)
        for part in parts
    )


def redacted_event_rows(
    event: Event,
    expected_evidence: Mapping[str, object],
) -> list[TimelineRow]:
    """Adapt one raw ADK event into fixed, allowlisted timeline rows."""
    rows: list[TimelineRow] = []
    for call in event.get_function_calls():
        rows.append(
            ("tool call", redact_tool_call(call, expected_evidence))
        )
    for response in event.get_function_responses():
        rows.append(
            (
                "tool result",
                redact_tool_result(response, expected_evidence),
            )
        )
    if getattr(event, "error_code", None):
        rows.append(("runtime error", REDACTED_RUNTIME_ERROR))
    if (
        event.author != "user"
        and event.is_final_response()
        and has_nonthought_final_text(event)
    ):
        rows.append(("final answer", FINAL_ANSWER_ACKNOWLEDGEMENT))
    return rows


def render_timeline(rows: Sequence[TimelineRow]) -> None:
    """Print only rows already reduced to safe public values."""
    print("Redacted runtime timeline")
    for stage, value in rows:
        print(f"{stage:13} | {value}")
