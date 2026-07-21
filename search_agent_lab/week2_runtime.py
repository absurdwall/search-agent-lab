"""Notebook-owned ADK runtime for the Week 2 learner lab."""

from __future__ import annotations

from collections.abc import Mapping
import atexit
import errno
import json
from pathlib import Path
import secrets
import socket
import threading
import time
from typing import Any
from urllib import error, parse, request

from google.adk.agents import Agent
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.cli.utils.base_agent_loader import BaseAgentLoader
import uvicorn

from .spooky_demo import summarize_events


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_USER_ID = "user"
WEEK_TOOL_NAME = "find_terms_by_week"


def _safe_week_arguments(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    introduced_in = value.get("introduced_in")
    return (
        {"introduced_in": introduced_in}
        if isinstance(introduced_in, str)
        else {}
    )


def _safe_week_result(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, object] = {
        key: value[key]
        for key in ("status", "introduced_in", "count", "reason")
        if key in value
        and isinstance(value.get(key), (str, int))
    }
    if isinstance(value.get("terms"), list):
        safe["terms"] = [
            {
                key: item[key]
                for key in ("id", "term", "canonical_url")
                if isinstance(item, Mapping)
                and isinstance(item.get(key), str)
            }
            for item in value["terms"]
            if isinstance(item, Mapping)
        ]
    return safe


def project_safe_timeline(
    events: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Project raw ADK JSON into the learner-safe Week 2 event surface."""
    timeline: list[dict[str, object]] = []
    for event_item in events:
        if not isinstance(event_item, Mapping):
            continue
        # Reuse the public glossary projection already locked by its own tests.
        timeline.extend(summarize_events([dict(event_item)]))
        identity = {
            output_key: event_item[input_key]
            for input_key, output_key in (
                ("id", "event_id"),
                ("invocationId", "invocation_id"),
            )
            if isinstance(event_item.get(input_key), str)
        }

        content = event_item.get("content")
        parts = content.get("parts") if isinstance(content, Mapping) else None
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            function_call = part.get("functionCall")
            if (
                isinstance(function_call, Mapping)
                and function_call.get("name") == WEEK_TOOL_NAME
            ):
                timeline.append(
                    {
                        "type": "function_call",
                        "name": WEEK_TOOL_NAME,
                        "arguments": _safe_week_arguments(function_call.get("args")),
                        **identity,
                    }
                )

            function_response = part.get("functionResponse")
            if (
                isinstance(function_response, Mapping)
                and function_response.get("name") == WEEK_TOOL_NAME
            ):
                timeline.append(
                    {
                        "type": "function_response",
                        "name": WEEK_TOOL_NAME,
                        "result": _safe_week_result(
                            function_response.get("response")
                        ),
                        **identity,
                    }
                )

    return timeline


class _RegistryAgentLoader(BaseAgentLoader):
    def __init__(self, registry: dict[str, Agent]):
        self._registry = registry

    def list_agents(self) -> list[str]:
        return sorted(self._registry)

    def load_agent(self, agent_name: str) -> Agent:
        try:
            return self._registry[agent_name]
        except KeyError as exc:
            raise ValueError(f"Unknown Notebook agent: {agent_name}") from exc


class Week2NotebookRuntime:
    """Own one local ADK Web server and its in-memory learner sessions."""

    def __init__(
        self,
        repository_root: Path,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        user_id: str = DEFAULT_USER_ID,
    ) -> None:
        self.repository_root = Path(repository_root).resolve()
        self.host = host
        self.preferred_port = port
        self.port = port
        self.user_id = user_id
        self.base_url = f"http://{host}:{port}"
        self.registry: dict[str, Agent] = {}
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None
        self._atexit_registered = False

    def _bind_server_socket(self) -> socket.socket:
        """Reserve the preferred port, or atomically select a free fallback."""
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET

        def bind(port: int) -> socket.socket:
            listener = socket.socket(family=family, type=socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind((self.host, port))
            except OSError:
                listener.close()
                raise
            listener.set_inheritable(True)
            return listener

        preferred_port = self.preferred_port
        try:
            listener = bind(preferred_port)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise RuntimeError(
                    f"ADK Web could not bind to {self.host}:{preferred_port}."
                ) from exc
            listener = bind(0)

        self.port = int(listener.getsockname()[1])
        self.base_url = f"http://{self.host}:{self.port}"
        return listener

    def _json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> Any:
        data = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {"Content-Type": "application/json"} if data else {}
        http_request = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with request.urlopen(http_request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))

    def start(self) -> None:
        """Start ADK Web on the preferred port or an available fallback."""
        if self._thread is not None and self._thread.is_alive():
            return
        self.stop()
        self._listener = self._bind_server_socket()

        try:
            web_app = get_fast_api_app(
                agents_dir=str(self.repository_root),
                agent_loader=_RegistryAgentLoader(self.registry),
                session_service_uri="memory://",
                web=True,
                host=self.host,
                port=self.port,
                reload_agents=False,
            )
            self._server = uvicorn.Server(
                uvicorn.Config(
                    web_app,
                    host=self.host,
                    port=self.port,
                    log_level="warning",
                    access_log=False,
                )
            )
        except Exception:
            self._listener.close()
            self._listener = None
            raise
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [self._listener]},
            daemon=True,
            name="week2-adk-web",
        )
        self._thread.start()
        for _ in range(100):
            try:
                if self._json_request("GET", "/health") == {"status": "ok"}:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            self.stop()
            raise RuntimeError(
                f"Notebook ADK Web did not become ready on port {self.port}."
            )
        if not self._atexit_registered:
            atexit.register(self.stop)
            self._atexit_registered = True

    def stop(self) -> None:
        """Stop the server; its in-memory sessions are intentionally lost."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=10)
        if self._listener is not None:
            self._listener.close()
        self._server = None
        self._thread = None
        self._listener = None

    def register_agent(self, app_name: str, agent: Agent) -> None:
        self.registry[app_name] = agent
        if self._thread is not None and self._thread.is_alive():
            loaded = self._json_request("GET", "/list-apps")
            if app_name not in loaded:
                raise RuntimeError(f"ADK Web did not load {app_name}.")

    def run_agent(self, app_name: str, question: str) -> dict[str, object]:
        """Run one fresh session and return only safe projected evidence."""
        session_id = f"{app_name}-{secrets.token_hex(3)}"
        safe_app = parse.quote(app_name, safe="")
        session = self._json_request(
            "POST",
            f"/apps/{safe_app}/users/{self.user_id}/sessions",
            {"sessionId": session_id},
        )
        if not isinstance(session, Mapping) or session.get("id") != session_id:
            raise RuntimeError("ADK did not create the requested fresh session.")

        http_status = 200
        try:
            returned = self._json_request(
                "POST",
                "/run",
                {
                    "appName": app_name,
                    "userId": self.user_id,
                    "sessionId": session_id,
                    "newMessage": {
                        "role": "user",
                        "parts": [{"text": question}],
                    },
                },
            )
        except error.HTTPError as exc:
            http_status = exc.code
            returned = []

        fetched = self._json_request(
            "GET",
            f"/apps/{safe_app}/users/{self.user_id}/sessions/"
            f"{parse.quote(session_id, safe='')}",
        )
        persisted_events = (
            fetched.get("events", []) if isinstance(fetched, Mapping) else []
        )
        events = (
            returned
            if isinstance(returned, list) and returned
            else persisted_events
        )
        if not isinstance(events, list):
            events = []
        safe_events = [event for event in events if isinstance(event, dict)]
        return {
            "app": app_name,
            "session_id": session_id,
            "question": question,
            "http_status": http_status,
            "timeline": project_safe_timeline(safe_events),
        }


def show_run(result: Mapping[str, object]) -> None:
    """Print identifiers plus the already allowlisted Notebook timeline."""
    print("App:", result.get("app"))
    print("Session:", result.get("session_id"))
    print("Question:", result.get("question"))
    print("HTTP status:", result.get("http_status"))
    timeline = result.get("timeline")
    if isinstance(timeline, list):
        for row in timeline:
            print(json.dumps(row, ensure_ascii=False))
