from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
import unittest
from unittest.mock import patch

from google.adk.events import Event
from google.auth.exceptions import GoogleAuthError
from google.genai import errors as genai_errors
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
    _adk_failure_category,
    _allowed_website_origins,
    _emit_provider_failure,
    _failure_category_for_status,
    _numeric_api_status,
    _provider_is_configured,
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
                self.assertEqual(
                    preflight.headers["Access-Control-Allow-Headers"],
                    "Accept, Accept-Language, Content-Language, Content-Type",
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


class ProviderConfigurationTests(unittest.TestCase):
    def assert_provider_configured(self, expected: bool, **environment: str) -> None:
        with patch.dict(os.environ, environment, clear=True):
            self.assertIs(_provider_is_configured(), expected)

    def test_developer_api_key_mode_requires_a_real_key(self) -> None:
        self.assert_provider_configured(True, GOOGLE_API_KEY="real-test-key")
        for value in ("", "   ", "your-own-key-goes-here"):
            with self.subTest(value=value):
                self.assert_provider_configured(False, GOOGLE_API_KEY=value)

    def test_canonical_google_cloud_mode_requires_project_and_location(
        self,
    ) -> None:
        for value in ("true", "TRUE", "True", "1"):
            with self.subTest(value=value):
                self.assert_provider_configured(
                    True,
                    GOOGLE_GENAI_USE_ENTERPRISE=value,
                    GOOGLE_CLOUD_PROJECT="search-agent-lab",
                    GOOGLE_CLOUD_LOCATION="global",
                )

        incomplete = (
            {
                "GOOGLE_GENAI_USE_ENTERPRISE": "true",
                "GOOGLE_CLOUD_LOCATION": "global",
            },
            {
                "GOOGLE_GENAI_USE_ENTERPRISE": "true",
                "GOOGLE_CLOUD_PROJECT": "search-agent-lab",
            },
            {
                "GOOGLE_GENAI_USE_ENTERPRISE": "true",
                "GOOGLE_CLOUD_PROJECT": "   ",
                "GOOGLE_CLOUD_LOCATION": "global",
            },
            {
                "GOOGLE_GENAI_USE_ENTERPRISE": "true",
                "GOOGLE_CLOUD_PROJECT": "search-agent-lab",
                "GOOGLE_CLOUD_LOCATION": "   ",
            },
        )
        for environment in incomplete:
            with self.subTest(environment=environment):
                self.assert_provider_configured(False, **environment)

    def test_legacy_vertex_flag_is_only_a_fallback(self) -> None:
        self.assert_provider_configured(
            True,
            GOOGLE_GENAI_USE_VERTEXAI="true",
            GOOGLE_CLOUD_PROJECT="search-agent-lab",
            GOOGLE_CLOUD_LOCATION="global",
        )
        self.assert_provider_configured(
            False,
            GOOGLE_GENAI_USE_VERTEXAI="1",
            GOOGLE_CLOUD_PROJECT="search-agent-lab",
        )

    def test_whitespace_mode_values_match_the_locked_sdk(self) -> None:
        for variable in (
            "GOOGLE_GENAI_USE_ENTERPRISE",
            "GOOGLE_GENAI_USE_VERTEXAI",
        ):
            for value in (" true ", " 1 "):
                cloud_environment = {
                    variable: value,
                    "GOOGLE_CLOUD_PROJECT": "search-agent-lab",
                    "GOOGLE_CLOUD_LOCATION": "global",
                }
                with self.subTest(variable=variable, value=value):
                    self.assert_provider_configured(False, **cloud_environment)
                    self.assert_provider_configured(
                        True,
                        **cloud_environment,
                        GOOGLE_API_KEY="real-test-key",
                    )

    def test_false_garbage_or_missing_mode_uses_developer_api_mode(self) -> None:
        self.assert_provider_configured(False)
        for value in ("false", "0", "yes", "garbage", ""):
            with self.subTest(value=value):
                self.assert_provider_configured(
                    False,
                    GOOGLE_GENAI_USE_ENTERPRISE=value,
                    GOOGLE_CLOUD_PROJECT="search-agent-lab",
                    GOOGLE_CLOUD_LOCATION="global",
                )
        self.assert_provider_configured(
            False,
            GOOGLE_CLOUD_PROJECT="search-agent-lab",
            GOOGLE_CLOUD_LOCATION="global",
        )

    def test_enterprise_flag_wins_conflicts_with_legacy_flag(self) -> None:
        cloud_environment = {
            "GOOGLE_GENAI_USE_ENTERPRISE": "false",
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
            "GOOGLE_CLOUD_PROJECT": "search-agent-lab",
            "GOOGLE_CLOUD_LOCATION": "global",
        }
        self.assert_provider_configured(False, **cloud_environment)
        self.assert_provider_configured(
            True,
            **cloud_environment,
            GOOGLE_API_KEY="real-test-key",
        )

    def test_selected_google_cloud_mode_takes_precedence_over_api_key(self) -> None:
        self.assert_provider_configured(
            True,
            GOOGLE_GENAI_USE_ENTERPRISE="true",
            GOOGLE_CLOUD_PROJECT="search-agent-lab",
            GOOGLE_CLOUD_LOCATION="global",
            GOOGLE_API_KEY="real-test-key",
        )
        self.assert_provider_configured(
            False,
            GOOGLE_GENAI_USE_ENTERPRISE="true",
            GOOGLE_CLOUD_PROJECT="search-agent-lab",
            GOOGLE_API_KEY="real-test-key",
        )


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


class RaisingRunner:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def run_async(self, **_values: object):
        self.calls += 1
        if False:
            yield None
        raise self.error


class ErrorEventRunner:
    def __init__(self, error_code: str, error_message: str) -> None:
        self.error_code = error_code
        self.error_message = error_message
        self.calls = 0

    async def run_async(self, **_values: object):
        self.calls += 1
        yield Event(
            author="spooky",
            errorCode=self.error_code,
            errorMessage=self.error_message,
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_function_response(
                        name="get_glossary_terms",
                        response={"tool_payload": self.error_message},
                    )
                ],
            ),
        )


class ProviderFailureDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def assert_one_diagnostic(self, output: str) -> dict[str, object]:
        lines = [line for line in output.splitlines() if line]
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(
            set(record),
            {
                "event",
                "request_id",
                "failure_source",
                "failure_category",
                "upstream_status",
                "severity",
                "message",
            },
        )
        self.assertEqual(record["event"], "spooky_provider_failure")
        self.assertEqual(record["severity"], "WARNING")
        self.assertEqual(
            record["message"], "Spooky provider failure classified."
        )
        return record

    def test_api_status_category_table(self) -> None:
        cases = {
            401: "authentication",
            403: "authorization",
            404: "model_or_location",
            408: "timeout",
            429: "quota_or_capacity",
            500: "provider_5xx",
            502: "provider_5xx",
            503: "provider_5xx",
            504: "timeout",
            418: "unknown",
            None: "unknown",
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                self.assertEqual(
                    _failure_category_for_status(status), expected
                )

    def test_only_plain_numeric_api_status_is_projected(self) -> None:
        class ErrorLike:
            def __init__(self, code: object) -> None:
                self.code = code

        for value, expected in (
            (503, 503),
            ("503", None),
            (True, None),
            (None, None),
            (-1, None),
            (99, None),
            (600, None),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    _numeric_api_status(ErrorLike(value)),  # type: ignore[arg-type]
                    expected,
                )

    def test_emitter_defensively_sanitizes_upstream_status(self) -> None:
        for value, expected in ((503, 503), (-1, None), (99, None), (600, None)):
            with self.subTest(value=value):
                output = io.StringIO()
                with redirect_stdout(output):
                    _emit_provider_failure(
                        request_id="req_status",
                        failure_source="genai_api",
                        failure_category="unknown",
                        upstream_status=value,
                    )
                record = self.assert_one_diagnostic(output.getvalue())
                self.assertEqual(record["upstream_status"], expected)

    def test_adk_codes_are_allowlisted_and_unknown_values_are_redacted(
        self,
    ) -> None:
        cases = {
            "UNAUTHENTICATED": "authentication",
            "PERMISSION_DENIED": "authorization",
            "NOT_FOUND": "model_or_location",
            "RESOURCE_EXHAUSTED": "quota_or_capacity",
            "DEADLINE_EXCEEDED": "timeout",
            "UNAVAILABLE": "provider_5xx",
            "MALFORMED_FUNCTION_CALL": "adk_error",
            "secret-raw-code=https://private.invalid": "adk_error",
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                self.assertEqual(_adk_failure_category(code), expected)

    async def test_genai_failure_emits_one_redacted_record_without_retry(
        self,
    ) -> None:
        sentinel = "credential=never-log-this"
        private_url = "https://private.invalid/model?token=never-log-this"
        prompt = "prompt-shaped never-log-this"
        error = genai_errors.APIError(
            503,
            {
                "error": {
                    "message": sentinel,
                    "url": private_url,
                    "body": prompt,
                }
            },
            httpx.Response(
                503,
                request=httpx.Request("POST", private_url),
                content=sentinel,
            ),
        )
        runner = RaisingRunner(error)
        sessions = FakeSessionService()
        service = AdkSpookyService(
            runner=runner,  # type: ignore[arg-type]
            session_service=sessions,  # type: ignore[arg-type]
            provider_is_configured=lambda: True,
        )
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(
            ProviderUnavailableError
        ):
            await service.chat(prompt, "req_provider_failure")

        rendered = output.getvalue()
        record = self.assert_one_diagnostic(rendered)
        self.assertEqual(record["request_id"], "req_provider_failure")
        self.assertEqual(record["failure_source"], "genai_api")
        self.assertEqual(record["failure_category"], "provider_5xx")
        self.assertEqual(record["upstream_status"], 503)
        for forbidden in (sentinel, private_url, prompt, "tool_payload"):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(len(sessions.created), 1)
        self.assertEqual(sessions.deleted, sessions.created)

    async def test_genai_504_keeps_timeout_response_and_cleanup(self) -> None:
        sentinel = "upstream-timeout=never-log-this"
        runner = RaisingRunner(
            genai_errors.APIError(
                504,
                {"error": {"message": sentinel}},
                httpx.Response(
                    504,
                    request=httpx.Request(
                        "POST", "https://private.invalid/timeout"
                    ),
                    content=sentinel,
                ),
            )
        )
        sessions = FakeSessionService()
        service = AdkSpookyService(
            runner=runner,  # type: ignore[arg-type]
            session_service=sessions,  # type: ignore[arg-type]
            provider_is_configured=lambda: True,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            response = await request(
                service,  # type: ignore[arg-type]
                "POST",
                "/v1/chat",
                json={"message": "What is a Tool?"},
            )

        record = self.assert_one_diagnostic(output.getvalue())
        self.assertEqual(record["failure_source"], "genai_api")
        self.assertEqual(record["failure_category"], "timeout")
        self.assertEqual(record["upstream_status"], 504)
        self.assertNotIn(sentinel, output.getvalue())
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error"]["code"], "REQUEST_TIMEOUT")
        self.assertEqual(runner.calls, 1)
        self.assertEqual(sessions.deleted, sessions.created)

    async def test_diagnostic_output_failure_does_not_change_api_outcome(
        self,
    ) -> None:
        cases = (
            (503, BrokenPipeError("closed pipe"), 503, "PROVIDER_UNAVAILABLE"),
            (504, OSError("closed stdout"), 504, "REQUEST_TIMEOUT"),
            (
                503,
                ValueError("I/O operation on closed file"),
                503,
                "PROVIDER_UNAVAILABLE",
            ),
        )
        for upstream, output_error, expected_status, expected_code in cases:
            with self.subTest(upstream=upstream, output_error=type(output_error)):
                runner = RaisingRunner(
                    genai_errors.APIError(
                        upstream,
                        {"error": {"message": "secret=never-log-this"}},
                    )
                )
                sessions = FakeSessionService()
                service = AdkSpookyService(
                    runner=runner,  # type: ignore[arg-type]
                    session_service=sessions,  # type: ignore[arg-type]
                    provider_is_configured=lambda: True,
                )
                with patch("builtins.print", side_effect=output_error):
                    response = await request(
                        service,  # type: ignore[arg-type]
                        "POST",
                        "/v1/chat",
                        json={"message": "What is a Tool?"},
                    )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(
                    response.json()["error"]["code"], expected_code
                )
                self.assertEqual(runner.calls, 1)
                self.assertEqual(sessions.deleted, sessions.created)

    async def test_adk_failure_logs_category_not_event_details(self) -> None:
        sentinel = "event-message-or-tool-payload=never-log-this"
        raw_code = "secret-raw-code=https://private.invalid"
        runner = ErrorEventRunner(raw_code, sentinel)
        sessions = FakeSessionService()
        service = AdkSpookyService(
            runner=runner,  # type: ignore[arg-type]
            session_service=sessions,  # type: ignore[arg-type]
            provider_is_configured=lambda: True,
        )
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(
            ProviderUnavailableError
        ):
            await service.chat(
                "prompt-shaped never-log-this", "req_adk_failure"
            )

        rendered = output.getvalue()
        record = self.assert_one_diagnostic(rendered)
        self.assertEqual(record["failure_source"], "adk_event")
        self.assertEqual(record["failure_category"], "adk_error")
        self.assertIsNone(record["upstream_status"])
        self.assertNotIn(raw_code, rendered)
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn("prompt-shaped", rendered)
        self.assertEqual(runner.calls, 1)
        self.assertEqual(sessions.deleted, sessions.created)

    async def test_readiness_failure_logs_only_configuration_category(
        self,
    ) -> None:
        sessions = FakeSessionService()
        service = AdkSpookyService(
            runner=FakeRunner(),  # type: ignore[arg-type]
            session_service=sessions,  # type: ignore[arg-type]
            provider_is_configured=lambda: False,
        )
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(
            ProviderUnavailableError
        ):
            await service.chat(
                "prompt-shaped never-log-this", "req_readiness"
            )

        rendered = output.getvalue()
        record = self.assert_one_diagnostic(rendered)
        self.assertEqual(record["failure_source"], "readiness")
        self.assertEqual(record["failure_category"], "configuration")
        self.assertIsNone(record["upstream_status"])
        self.assertNotIn("prompt-shaped", rendered)
        self.assertEqual(sessions.created, [])
        self.assertEqual(sessions.deleted, [])

    async def test_transport_and_auth_failures_use_fixed_categories(
        self,
    ) -> None:
        sentinel = "exception-message=never-log-this"
        cases = (
            (
                httpx.TimeoutException(
                    sentinel,
                    request=httpx.Request(
                        "POST", "https://private.invalid/timeout"
                    ),
                ),
                TimeoutError,
                "http_transport",
                "timeout",
            ),
            (
                GoogleAuthError(sentinel),
                ProviderUnavailableError,
                "google_auth",
                "authentication",
            ),
            (
                httpx.ConnectError(
                    sentinel,
                    request=httpx.Request(
                        "POST", "https://private.invalid/connect"
                    ),
                ),
                ProviderUnavailableError,
                "http_transport",
                "transport",
            ),
            (
                ConnectionError(sentinel),
                ProviderUnavailableError,
                "http_transport",
                "transport",
            ),
            (
                OSError(sentinel),
                ProviderUnavailableError,
                "os_transport",
                "transport",
            ),
        )
        for error, raised, source, category in cases:
            with self.subTest(source=source, category=category):
                runner = RaisingRunner(error)
                service = AdkSpookyService(
                    runner=runner,  # type: ignore[arg-type]
                    session_service=FakeSessionService(),  # type: ignore[arg-type]
                    provider_is_configured=lambda: True,
                )
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaises(raised):
                    await service.chat("safe prompt", "req_transport")
                rendered = output.getvalue()
                record = self.assert_one_diagnostic(rendered)
                self.assertEqual(record["failure_source"], source)
                self.assertEqual(record["failure_category"], category)
                self.assertIsNone(record["upstream_status"])
                self.assertNotIn(sentinel, rendered)
                self.assertNotIn("private.invalid", rendered)
                self.assertEqual(runner.calls, 1)


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
