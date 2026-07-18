"""Narrow, single-turn HTTP boundary for the Spooky glossary agent."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import secrets
from typing import Protocol
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.auth.exceptions import GoogleAuthError
from google.genai import errors as genai_errors
from google.genai import types
import httpx
from pydantic import BaseModel, ConfigDict
from dotenv import load_dotenv

from spooky.agent import root_agent
from spooky.tools import EXPECTED_IDS, get_glossary_terms


APP_NAME = "spooky"
INTERNAL_USER_ID = "spooky-web"
MAX_MESSAGE_CHARS = 2_000
CHAT_TIMEOUT_SECONDS = 120
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCAL_WEBSITE_ORIGINS = (
    "http://127.0.0.1:8765",
    "http://localhost:8765",
)
PUBLIC_WEBSITE_ORIGIN = "https://absurdwall.github.io"
DEFAULT_WEBSITE_ORIGINS = LOCAL_WEBSITE_ORIGINS + (PUBLIC_WEBSITE_ORIGIN,)
ALLOWED_WEBSITE_ORIGINS_ENV = "SPOOKY_ALLOWED_ORIGINS"

_EXPECTED_ID_SET = frozenset(EXPECTED_IDS)
_LOGGER = logging.getLogger(__name__)


class Source(BaseModel):
    """One canonical glossary page used by Spooky."""

    model_config = ConfigDict(extra="forbid")

    title: str
    url: str


class ChatRequest(BaseModel):
    """The only browser-controlled input accepted by the API."""

    model_config = ConfigDict(extra="forbid")

    message: str


class ChatResponse(BaseModel):
    """Stable, allowlisted successful response."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    sources: list[Source]
    request_id: str


class ErrorDetail(BaseModel):
    """Stable public error without internal details."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Stable error envelope."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
    request_id: str


@dataclass(frozen=True)
class ChatResult:
    """Safe result returned by the internal Spooky adapter."""

    answer: str
    sources: tuple[Source, ...]


class ChatService(Protocol):
    """Small seam that keeps HTTP tests independent from Gemini."""

    async def chat(self, message: str, request_id: str) -> ChatResult: ...


class ProviderUnavailableError(RuntimeError):
    """The configured model provider cannot serve the request."""


def _request_id() -> str:
    return f"req_{secrets.token_urlsafe(12)}"


def _provider_is_configured() -> bool:
    value = os.getenv("GOOGLE_API_KEY", "").strip()
    return bool(value and value != "your-own-key-goes-here")


def _allowed_website_origins() -> tuple[str, ...]:
    """Return an exact CORS allowlist, rejecting wildcard-like configuration."""
    configured = os.getenv(ALLOWED_WEBSITE_ORIGINS_ENV)
    if configured is None:
        return DEFAULT_WEBSITE_ORIGINS

    candidates = tuple(origin.strip() for origin in configured.split(","))
    if not candidates or any(not origin for origin in candidates):
        raise ValueError(
            f"{ALLOWED_WEBSITE_ORIGINS_ENV} must contain exact origins."
        )

    origins: list[str] = []
    for origin in candidates:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in origin
        ):
            raise ValueError(
                f"{ALLOWED_WEBSITE_ORIGINS_ENV} must contain exact HTTP(S) "
                "origins without credentials, paths, queries, fragments, or "
                "wildcards."
            )
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)


def _result_payload(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    output = value.get("output")
    return output if isinstance(output, Mapping) else value


def _retrieved_term_ids(event: Event) -> list[str]:
    term_ids: list[str] = []
    for response in event.get_function_responses():
        if response.name != "get_glossary_terms":
            continue
        payload = _result_payload(response.response)
        terms = payload.get("terms") if payload is not None else None
        if not isinstance(terms, list):
            continue
        for term in terms:
            term_id = term.get("id") if isinstance(term, Mapping) else None
            if (
                isinstance(term_id, str)
                and term_id in _EXPECTED_ID_SET
                and term_id not in term_ids
            ):
                term_ids.append(term_id)
    return term_ids


def _final_answer(event: Event) -> str | None:
    if event.author != root_agent.name or not event.is_final_response():
        return None
    if event.content is None or not event.content.parts:
        return None
    text = "".join(
        part.text
        for part in event.content.parts
        if isinstance(part.text, str) and part.text and part.thought is not True
    ).strip()
    return text or None


def _canonical_sources(term_ids: list[str]) -> tuple[Source, ...]:
    """Rehydrate allowlisted IDs from the pinned snapshot, never event URLs."""
    if not term_ids:
        return ()
    records = get_glossary_terms(term_ids).get("terms", [])
    sources: list[Source] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        title = record.get("term")
        url = record.get("canonical_url")
        if isinstance(title, str) and isinstance(url, str):
            sources.append(Source(title=title, url=url))
    return tuple(sources)


class AdkSpookyService:
    """Run one Spooky turn in a temporary, deleted ADK session."""

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        session_service: InMemorySessionService | None = None,
        provider_is_configured: Callable[[], bool] = _provider_is_configured,
    ) -> None:
        load_dotenv(REPOSITORY_ROOT / ".env", override=False)
        self._session_service = session_service or InMemorySessionService()
        self._runner = runner or Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=self._session_service,
        )
        self._provider_is_configured = provider_is_configured

    async def chat(self, message: str, request_id: str) -> ChatResult:
        if not self._provider_is_configured():
            raise ProviderUnavailableError

        await self._session_service.create_session(
            app_name=APP_NAME,
            user_id=INTERNAL_USER_ID,
            session_id=request_id,
        )
        answer: str | None = None
        term_ids: list[str] = []
        try:
            new_message = types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)],
            )
            async for event in self._runner.run_async(
                user_id=INTERNAL_USER_ID,
                session_id=request_id,
                new_message=new_message,
            ):
                if event.error_code:
                    raise ProviderUnavailableError
                for term_id in _retrieved_term_ids(event):
                    if term_id not in term_ids:
                        term_ids.append(term_id)
                final_answer = _final_answer(event)
                if final_answer is not None:
                    answer = final_answer
        except httpx.TimeoutException as exc:
            raise TimeoutError from exc
        except genai_errors.APIError as exc:
            if exc.code in {408, 504}:
                raise TimeoutError from exc
            raise ProviderUnavailableError from exc
        except (httpx.HTTPError, GoogleAuthError, ConnectionError, OSError) as exc:
            raise ProviderUnavailableError from exc
        finally:
            try:
                await self._session_service.delete_session(
                    app_name=APP_NAME,
                    user_id=INTERNAL_USER_ID,
                    session_id=request_id,
                )
            except Exception:
                _LOGGER.warning(
                    "Temporary Spooky session cleanup failed for request_id=%s",
                    request_id,
                )

        if answer is None:
            raise RuntimeError("Spooky produced no final answer")
        return ChatResult(answer=answer, sources=_canonical_sources(term_ids))


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    request_id = request.state.request_id
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message),
        request_id=request_id,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def create_app(service: ChatService | None = None) -> FastAPI:
    """Build the narrow API; callers may inject a deterministic test service."""
    chat_service = service or AdkSpookyService()
    api = FastAPI(
        title="Spooky API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=list(_allowed_website_origins()),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )

    @api.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = _request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @api.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=400,
            code="INVALID_REQUEST",
            message="Request body must contain only a string message.",
        )

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post(
        "/v1/chat",
        response_model=ChatResponse,
        responses={
            400: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
        },
    )
    async def chat(payload: ChatRequest, request: Request):
        if len(payload.message) > MAX_MESSAGE_CHARS:
            return _error_response(
                request,
                status_code=413,
                code="MESSAGE_TOO_LARGE",
                message=f"message must be at most {MAX_MESSAGE_CHARS} characters.",
            )
        message = payload.message.strip()
        if not message:
            return _error_response(
                request,
                status_code=400,
                code="EMPTY_MESSAGE",
                message="message must contain non-whitespace characters.",
            )

        try:
            async with asyncio.timeout(CHAT_TIMEOUT_SECONDS):
                result = await chat_service.chat(
                    message, request.state.request_id
                )
        except ProviderUnavailableError:
            return _error_response(
                request,
                status_code=503,
                code="PROVIDER_UNAVAILABLE",
                message="Spooky's model provider is unavailable. Try again later.",
            )
        except TimeoutError:
            return _error_response(
                request,
                status_code=504,
                code="REQUEST_TIMEOUT",
                message="Spooky did not respond before the timeout.",
            )
        except Exception as exc:
            _LOGGER.error(
                "Spooky request failed: request_id=%s exception_type=%s",
                request.state.request_id,
                type(exc).__name__,
            )
            return _error_response(
                request,
                status_code=500,
                code="INTERNAL_ERROR",
                message="Spooky could not complete the request.",
            )

        return ChatResponse(
            answer=result.answer,
            sources=list(result.sources),
            request_id=request.state.request_id,
        )

    return api


app = create_app()
