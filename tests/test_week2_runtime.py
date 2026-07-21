from __future__ import annotations

from pathlib import Path
import socket
import unittest

from google.adk.agents import Agent
from google.genai import types

from search_agent_lab.week2_runtime import (
    Week2NotebookRuntime,
    project_safe_timeline,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class Week2RuntimeTests(unittest.TestCase):
    def test_safe_timeline_reuses_glossary_projection(self) -> None:
        events = [
            {
                "id": "response",
                "invocationId": "invocation",
                "author": "grounded-agent",
                "content": {
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "search_glossary",
                                "response": {
                                    "status": "ok",
                                    "query": "Tool",
                                    "results": [
                                        {
                                            "id": "tool",
                                            "term": "Tool",
                                            "simple_definition": "A capability.",
                                            "match": {
                                                "kind": "exact",
                                                "fields": ["term"],
                                            },
                                            "secret": "drop",
                                        }
                                    ],
                                },
                            }
                        }
                    ]
                },
            }
        ]
        timeline = project_safe_timeline(events)
        self.assertEqual(timeline[0]["type"], "function_response")
        self.assertEqual(timeline[0]["name"], "search_glossary")
        self.assertNotIn("secret", repr(timeline))

    def test_safe_timeline_allowlists_week_lookup_evidence(self) -> None:
        events = [
            {
                "id": "call",
                "invocationId": "invocation",
                "author": "week-agent",
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "find_terms_by_week",
                                "args": {
                                    "introduced_in": "week-01",
                                    "secret": "drop",
                                },
                            }
                        }
                    ]
                },
            },
            {
                "id": "response",
                "invocationId": "invocation",
                "author": "week-agent",
                "content": {
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "find_terms_by_week",
                                "response": {
                                    "status": "ok",
                                    "introduced_in": "week-01",
                                    "count": 1,
                                    "terms": [
                                        {
                                            "id": "tool",
                                            "term": "Tool",
                                            "canonical_url": "https://example.test/#tool",
                                            "secret": "drop",
                                        }
                                    ],
                                    "secret": "drop",
                                },
                            }
                        }
                    ]
                },
            },
        ]
        timeline = project_safe_timeline(events)
        rendered = repr(timeline)
        self.assertEqual([row["type"] for row in timeline], [
            "function_call",
            "function_response",
        ])
        self.assertNotIn("secret", rendered)
        self.assertEqual(
            timeline[1]["result"]["terms"][0]["id"],
            "tool",
        )

    def test_runtime_exposes_registered_agent_without_model_call(self) -> None:
        requested_port = free_port()
        runtime = Week2NotebookRuntime(REPOSITORY_ROOT, port=requested_port)
        try:
            runtime.start()
            self.assertEqual(runtime.port, requested_port)
            self.assertEqual(
                runtime.base_url,
                f"http://127.0.0.1:{requested_port}",
            )
            semantic_agent = Agent(
                name="semantic_test_agent",
                model="gemini-3.5-flash",
                generate_content_config=types.GenerateContentConfig(
                    temperature=0
                ),
            )
            runtime.register_agent("semantic_test_agent", semantic_agent)
            self.assertIn("semantic_test_agent", runtime.registry)
        finally:
            runtime.stop()

    def test_runtime_uses_free_fallback_without_stopping_port_owner(self) -> None:
        with socket.socket() as port_owner:
            port_owner.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            port_owner.bind(("127.0.0.1", 0))
            port_owner.listen()
            occupied_port = int(port_owner.getsockname()[1])
            runtime = Week2NotebookRuntime(
                REPOSITORY_ROOT,
                port=occupied_port,
            )
            try:
                runtime.start()
                self.assertEqual(runtime.preferred_port, occupied_port)
                self.assertNotEqual(runtime.port, occupied_port)
                self.assertEqual(
                    runtime.base_url,
                    f"http://127.0.0.1:{runtime.port}",
                )
                with socket.create_connection(
                    ("127.0.0.1", occupied_port),
                    timeout=1,
                ):
                    pass
            finally:
                runtime.stop()

            with socket.create_connection(
                ("127.0.0.1", occupied_port),
                timeout=1,
            ):
                pass


if __name__ == "__main__":
    unittest.main()
