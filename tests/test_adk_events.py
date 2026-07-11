from __future__ import annotations

import json
import unittest

from google.adk.events import Event
from google.genai import types

from search_agent_lab.checkpoints import WEEK_01, expected_evidence
from search_agent_lab.checks.adk_events import (
    FINAL_ANSWER_ACKNOWLEDGEMENT,
    REDACTED_RUNTIME_ERROR,
    redacted_event_rows,
)


EXPECTED = expected_evidence(WEEK_01)


def event_with_part(part: types.Part) -> Event:
    return Event(
        author="setup_agent",
        content=types.Content(role="model", parts=[part]),
    )


class SafeAdkEventTests(unittest.TestCase):
    def test_expected_tool_call_is_allowlisted(self) -> None:
        event = event_with_part(
            types.Part(
                function_call=types.FunctionCall(
                    name=EXPECTED["tool"],
                    args={"topic": EXPECTED["topic"]},
                )
            )
        )
        self.assertEqual(
            redacted_event_rows(event, EXPECTED),
            [
                (
                    "tool call",
                    {
                        "tool": EXPECTED["tool"],
                        "arguments": {"topic": EXPECTED["topic"]},
                    },
                )
            ],
        )

    def test_unexpected_tool_name_is_redacted(self) -> None:
        event = event_with_part(
            types.Part(
                function_call=types.FunctionCall(
                    name="secret_tool",
                    args={"topic": "AIza-secret-value"},
                )
            )
        )
        rows = redacted_event_rows(event, EXPECTED)
        self.assertEqual(rows, [("tool call", {"redacted": True})])
        self.assertNotIn("secret_tool", json.dumps(rows))
        self.assertNotIn("AIza-secret-value", json.dumps(rows))

    def test_expected_tool_result_is_allowlisted(self) -> None:
        event = event_with_part(
            types.Part(
                function_response=types.FunctionResponse(
                    name=EXPECTED["tool"],
                    response={
                        "status": EXPECTED["status"],
                        "topic": EXPECTED["topic"],
                        "summary": EXPECTED["summary"],
                    },
                )
            )
        )
        self.assertEqual(
            redacted_event_rows(event, EXPECTED),
            [
                (
                    "tool result",
                    {
                        "tool": EXPECTED["tool"],
                        "result": {
                            "status": EXPECTED["status"],
                            "topic": EXPECTED["topic"],
                            "summary": EXPECTED["summary"],
                        },
                    },
                )
            ],
        )

    def test_changed_result_fields_are_redacted(self) -> None:
        secret = "token=do-not-reflect"
        event = event_with_part(
            types.Part(
                function_response=types.FunctionResponse(
                    name=EXPECTED["tool"],
                    response={
                        "status": "changed",
                        "topic": EXPECTED["topic"],
                        "summary": secret,
                    },
                )
            )
        )
        rows = redacted_event_rows(event, EXPECTED)
        result = rows[0][1]
        assert isinstance(result, dict)
        self.assertEqual(
            result["result"],
            {
                "status": "redacted",
                "topic": EXPECTED["topic"],
                "summary": "redacted",
            },
        )
        self.assertNotIn(secret, json.dumps(rows))

    def test_thought_only_text_does_not_create_final_row(self) -> None:
        event = event_with_part(
            types.Part(text="private reasoning", thought=True)
        )
        self.assertEqual(redacted_event_rows(event, EXPECTED), [])

    def test_final_response_returns_only_fixed_acknowledgement(self) -> None:
        secret_model_text = "raw external model response"
        event = event_with_part(types.Part(text=secret_model_text))
        rows = redacted_event_rows(event, EXPECTED)
        self.assertEqual(
            rows,
            [("final answer", FINAL_ANSWER_ACKNOWLEDGEMENT)],
        )
        self.assertNotIn(secret_model_text, json.dumps(rows))

    def test_runtime_error_returns_fixed_redaction(self) -> None:
        secret_error = "authorization=secret-value"
        event = Event(
            author="setup_agent",
            error_code="UNAVAILABLE",
            error_message=secret_error,
        )
        rows = redacted_event_rows(event, EXPECTED)
        self.assertEqual(
            rows,
            [("runtime error", REDACTED_RUNTIME_ERROR)],
        )
        self.assertNotIn(secret_error, json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
