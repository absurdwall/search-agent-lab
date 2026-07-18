from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from google.adk.events import Event
from google.genai import types
import httpx

from search_agent_lab.spooky_api import (
    APP_NAME,
    ALLOWED_WEBSITE_ORIGINS_ENV,
    DEFAULT_WEBSITE_ORIGINS,
    INTERNAL_USER_ID,
    LOCAL_WEBSITE_ORIGINS,
    MAX_MESSAGE_CHARS,
    PUBLIC_WEBSITE_ORIGIN,
    AdkSpookyService,
    ChatResult,
    ProviderUnavailableError,
    Source,
    _canonical_sources,
    _final_answer,
    _allowed_website_origins,
    _retrieved_term_ids,
    create_app,
)


class FakeService:
    def __init__(self, result: ChatResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def chat(self, message: str, request_id: str) -> ChatResult:
        self.calls.append((message, request_id))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


async def request(
    service: FakeService, method: str, path: str, **kwargs: object
) -> httpx.Response:
    transport = httpx.ASGITransport(app=create_app(service))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.request(method, path, **kwargs)


class SpookyApiContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_health(self) -> None:
        response = await request(FakeService(), "GET", "/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertTrue(response.headers["X-Request-ID"].startswith("req_"))

    async def test_allowed_website_origins_receive_narrow_cors_headers(
        self,
    ) -> None:
        for origin in DEFAULT_WEBSITE_ORIGINS:
            with self.subTest(origin=origin):
                service = FakeService(
                    ChatResult(answer="Safe answer.", sources=())
                )
                health = await request(
                    service, "GET", "/health", headers={"Origin": origin}
                )
                chat = await request(
                    service,
                    "POST",
                    "/v1/chat",
                    headers={"Origin": origin},
                    json={"message": "What is a Tool?"},
                )
                preflight = await request(
                    service,
                    "OPTIONS",
                    "/v1/chat",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "content-type",
                    },
                )

                self.assertEqual(
                    health.headers["Access-Control-Allow-Origin"], origin
                )
                self.assertEqual(chat.status_code, 200)
                self.assertEqual(chat.json()["answer"], "Safe answer.")
                self.assertEqual(
                    chat.headers["Access-Control-Allow-Origin"], origin
                )
                self.assertEqual(
                    chat.headers["Access-Control-Expose-Headers"],
                    "X-Request-ID",
                )
                self.assertNotIn(
                    "Access-Control-Allow-Credentials", chat.headers
                )
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(
                    preflight.headers["Access-Control-Allow-Origin"], origin
                )
                self.assertEqual(
                    preflight.headers["Access-Control-Allow-Methods"], "GET, POST"
                )
                self.assertIn(
                    "content-type",
                    preflight.headers["Access-Control-Allow-Headers"].lower(),
                )
                self.assertNotIn(
                    "Access-Control-Allow-Credentials", preflight.headers
                )
                self.assertEqual(len(service.calls), 1)

    async def test_public_github_pages_origin_is_allowed(self) -> None:
        service = FakeService(ChatResult(answer="Safe answer.", sources=()))
        response = await request(
            service,
            "POST",
            "/v1/chat",
            headers={"Origin": PUBLIC_WEBSITE_ORIGIN},
            json={"message": "What is a Tool?"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            PUBLIC_WEBSITE_ORIGIN,
        )

    async def test_cors_environment_override_remains_an_exact_allowlist(
        self,
    ) -> None:
        configured_origin = "https://preview.example"
        with patch.dict(
            os.environ,
            {ALLOWED_WEBSITE_ORIGINS_ENV: configured_origin},
        ):
            service = FakeService(ChatResult(answer="Safe answer.", sources=()))
            response = await request(
                service,
                "POST",
                "/v1/chat",
                headers={"Origin": configured_origin},
                json={"message": "What is a Tool?"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            configured_origin,
        )

    def test_cors_environment_rejects_unsafe_origins(self) -> None:
        unsafe_values = (
            "*",
            "https://*.example.com",
            "https://user:password@example.com",
            "https://example.com/path",
            "https://example.com?query=yes",
            "https://example.com#fragment",
            "https://example.com,",
        )
        for value in unsafe_values:
            with self.subTest(value=value), patch.dict(
                os.environ,
                {ALLOWED_WEBSITE_ORIGINS_ENV: value},
            ):
                with self.assertRaises(ValueError):
                    _allowed_website_origins()

    async def test_disallowed_origin_receives_no_allow_origin_header(self) -> None:
        origin = "http://127.0.0.1:9999"
        service = FakeService(ChatResult(answer="Safe answer.", sources=()))
        chat = await request(
            service,
            "POST",
            "/v1/chat",
            headers={"Origin": origin},
            json={"message": "What is a Tool?"},
        )
        preflight = await request(
            service,
            "OPTIONS",
            "/v1/chat",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        self.assertEqual(chat.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", chat.headers)
        self.assertEqual(preflight.status_code, 400)
        self.assertNotIn("Access-Control-Allow-Origin", preflight.headers)

    async def test_cors_keeps_safe_error_envelope_unchanged(self) -> None:
        response = await request(
            FakeService(),
            "POST",
            "/v1/chat",
            headers={"Origin": LOCAL_WEBSITE_ORIGINS[0]},
            json={"message": "   "},
        )
        body = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            body["error"],
            {
                "code": "EMPTY_MESSAGE",
                "message": "message must contain non-whitespace characters.",
            },
        )
        self.assertEqual(set(body), {"error", "request_id"})
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            LOCAL_WEBSITE_ORIGINS[0],
        )

    async def test_success_is_stable_and_trims_input(self) -> None:
        service = FakeService(
            ChatResult(
                answer="A Tool is a callable capability.",
                sources=(
                    Source(
                        title="Tool",
                        url="https://absurdwall.github.io/"
                        "search-agent-study-group/glossary/#tool",
                    ),
                ),
            )
        )
        response = await request(
            service,
            "POST",
            "/v1/chat",
            json={"message": "  What is a Tool?  "},
        )
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(body), {"answer", "sources", "request_id"}
        )
        self.assertEqual(body["answer"], "A Tool is a callable capability.")
        self.assertEqual(body["sources"][0]["title"], "Tool")
        self.assertEqual(service.calls[0][0], "What is a Tool?")
        self.assertEqual(service.calls[0][1], body["request_id"])
        self.assertEqual(response.headers["X-Request-ID"], body["request_id"])

    async def test_empty_and_oversized_messages_are_rejected_without_service_call(
        self,
    ) -> None:
        service = FakeService()
        empty = await request(
            service, "POST", "/v1/chat", json={"message": " \n\t "}
        )
        oversized = await request(
            service,
            "POST",
            "/v1/chat",
            json={"message": "x" * (MAX_MESSAGE_CHARS + 1)},
        )
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(empty.json()["error"]["code"], "EMPTY_MESSAGE")
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(
            oversized.json()["error"]["code"], "MESSAGE_TOO_LARGE"
        )
        self.assertEqual(service.calls, [])

    async def test_malformed_bodies_have_one_safe_error_shape(self) -> None:
        service = FakeService()
        responses = (
            await request(service, "POST", "/v1/chat", json={}),
            await request(service, "POST", "/v1/chat", json={"message": 7}),
            await request(
                service,
                "POST",
                "/v1/chat",
                json={"message": "hi", "trace": True},
            ),
            await request(
                service,
                "POST",
                "/v1/chat",
                content="not-json",
                headers={"content-type": "application/json"},
            ),
        )
        for response in responses:
            with self.subTest(body=response.text):
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["error"]["code"], "INVALID_REQUEST"
                )
                self.assertEqual(
                    set(response.json()), {"error", "request_id"}
                )

    async def test_provider_timeout_and_internal_failures_are_safely_mapped(
        self,
    ) -> None:
        secret = "credential=never-return-this"
        cases = (
            (ProviderUnavailableError(secret), 503, "PROVIDER_UNAVAILABLE"),
            (TimeoutError(secret), 504, "REQUEST_TIMEOUT"),
            (RuntimeError(secret), 500, "INTERNAL_ERROR"),
        )
        for error, status, code in cases:
            with self.subTest(code=code):
                response = await request(
                    FakeService(error=error),
                    "POST",
                    "/v1/chat",
                    json={"message": "What is a Tool?"},
                )
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn(secret, response.text)


class EventProjectionTests(unittest.TestCase):
    def test_sources_use_only_ids_and_the_pinned_snapshot(self) -> None:
        secret = "https://attacker.invalid/private?token=secret"
        event = Event(
            author="spooky",
            content=types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name="get_glossary_terms",
                        response={
                            "status": "ok",
                            "terms": [
                                {
                                    "id": "tool",
                                    "term": "Malicious title",
                                    "canonical_url": secret,
                                    "arbitrary": {"trace": secret},
                                },
                                {"id": "not-in-pinned-glossary", "term": secret},
                            ],
                        },
                    )
                ],
            ),
        )
        term_ids = _retrieved_term_ids(event)
        sources = _canonical_sources(term_ids)
        rendered = json.dumps([source.model_dump() for source in sources])
        self.assertEqual(term_ids, ["tool"])
        self.assertEqual(sources[0].title, "Tool")
        self.assertTrue(sources[0].url.endswith("#tool"))
        self.assertNotIn(secret, rendered)
        self.assertNotIn("Malicious title", rendered)

    def test_final_answer_omits_thought_text(self) -> None:
        event = Event(
            author="spooky",
            content=types.Content(
                role="model",
                parts=[
                    types.Part(text="private reasoning", thought=True),
                    types.Part.from_text(text="Safe learner answer."),
                ],
            ),
        )
        self.assertEqual(_final_answer(event), "Safe learner answer.")


class FakeSessionService:
    def __init__(self) -> None:
        self.created: list[dict[str, str]] = []
        self.deleted: list[dict[str, str]] = []

    async def create_session(self, **values: str) -> None:
        self.created.append(values)

    async def delete_session(self, **values: str) -> None:
        self.deleted.append(values)


class FakeRunner:
    async def run_async(self, **_values: object):
        yield Event(
            author="spooky",
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text="Safe answer.")],
            ),
        )


class FailingRunner:
    async def run_async(self, **_values: object):
        if False:
            yield None
        raise RuntimeError("private provider detail")


class TemporarySessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_creates_and_deletes_one_internal_session(self) -> None:
        sessions = FakeSessionService()
        service = AdkSpookyService(
            runner=FakeRunner(),  # type: ignore[arg-type]
            session_service=sessions,  # type: ignore[arg-type]
            provider_is_configured=lambda: True,
        )
        result = await service.chat("What is a Tool?", "req_test")
        expected = {
            "app_name": APP_NAME,
            "user_id": INTERNAL_USER_ID,
            "session_id": "req_test",
        }
        self.assertEqual(result.answer, "Safe answer.")
        self.assertEqual(sessions.created, [expected])
        self.assertEqual(sessions.deleted, [expected])

    async def test_service_deletes_session_when_runner_fails(self) -> None:
        sessions = FakeSessionService()
        service = AdkSpookyService(
            runner=FailingRunner(),  # type: ignore[arg-type]
            session_service=sessions,  # type: ignore[arg-type]
            provider_is_configured=lambda: True,
        )
        with self.assertRaises(RuntimeError):
            await service.chat("What is a Tool?", "req_failure")
        self.assertEqual(
            sessions.deleted,
            [
                {
                    "app_name": APP_NAME,
                    "user_id": INTERNAL_USER_ID,
                    "session_id": "req_failure",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
