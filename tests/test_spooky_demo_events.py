from __future__ import annotations

import json
import unittest

from search_agent_lab.spooky_demo import summarize_events


def event(
    part: dict[str, object],
    *,
    event_id: str = "event-1",
    invocation_id: str = "invocation-1",
    **extra: object,
) -> dict[str, object]:
    return {
        "id": event_id,
        "invocationId": invocation_id,
        "author": "spooky",
        "content": {"role": "model", "parts": [part]},
        **extra,
    }


class SpookyDemoEventTests(unittest.TestCase):
    def test_function_call_is_included_with_ids(self) -> None:
        rows = summarize_events(
            [
                event(
                    {
                        "functionCall": {
                            "name": "search_glossary",
                            "args": {
                                "query": "tool and skill",
                                "secret": "do-not-copy",
                            },
                        }
                    }
                )
            ]
        )
        self.assertEqual(
            rows,
            [
                {
                    "type": "function_call",
                    "name": "search_glossary",
                    "arguments": {"query": "tool and skill"},
                    "event_id": "event-1",
                    "invocation_id": "invocation-1",
                }
            ],
        )

    def test_function_response_is_allowlisted(self) -> None:
        rows = summarize_events(
            [
                event(
                    {
                        "functionResponse": {
                            "name": "search_glossary",
                            "response": {
                                "status": "ok",
                                "query": "tool",
                                "results": [
                                    {
                                        "id": "tool",
                                        "term": "Tool",
                                        "simple_definition": "A capability.",
                                        "match": {
                                            "kind": "exact",
                                            "fields": ["term"],
                                            "private": "hidden",
                                        },
                                        "secret": "hidden",
                                    }
                                ],
                                "token": "hidden",
                            },
                        }
                    }
                )
            ]
        )
        self.assertEqual(rows[0]["type"], "function_response")
        self.assertEqual(rows[0]["result"]["results"][0]["id"], "tool")
        self.assertNotIn("hidden", json.dumps(rows))

    def test_final_non_thought_text_is_included(self) -> None:
        rows = summarize_events([event({"text": "Grounded final answer."})])
        self.assertEqual(rows[0]["type"], "final_text")
        self.assertEqual(rows[0]["text"], "Grounded final answer.")

    def test_thought_content_and_signatures_are_excluded(self) -> None:
        secret = "private-chain-of-thought"
        rows = summarize_events(
            [
                {
                    "id": "event-2",
                    "invocationId": "invocation-1",
                    "author": "spooky",
                    "content": {
                        "parts": [
                            {
                                "text": secret,
                                "thought": True,
                                "thoughtSignature": "signature-secret",
                            },
                            {"text": "Safe final."},
                        ]
                    },
                }
            ]
        )
        rendered = json.dumps(rows)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("signature-secret", rendered)
        self.assertEqual(rows[0]["text"], "Safe final.")

    def test_unknown_payloads_and_secret_fields_are_excluded(self) -> None:
        secret = "authorization=not-a-real-secret"
        rows = summarize_events(
            [
                event(
                    {"unknownPayload": {"credential": secret}},
                    customMetadata={"environment": secret},
                )
            ]
        )
        self.assertEqual(rows, [])
        self.assertNotIn(secret, json.dumps(rows))

    def test_safe_error_is_fixed_and_raw_message_is_excluded(self) -> None:
        secret = "authorization=secret"
        rows = summarize_events(
            [event({}, errorCode="UNAVAILABLE", errorMessage=secret)]
        )
        self.assertEqual(rows[0]["type"], "error")
        self.assertEqual(rows[0]["code"], "UNAVAILABLE")
        self.assertNotIn(secret, json.dumps(rows))

    def test_unknown_tool_is_excluded(self) -> None:
        rows = summarize_events(
            [
                event(
                    {
                        "functionCall": {
                            "name": "read_environment",
                            "args": {"path": "/private/path"},
                        }
                    }
                )
            ]
        )
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
