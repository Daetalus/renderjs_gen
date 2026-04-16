from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterator


@dataclass
class RecordedRequest:
    path: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass
class ServerState:
    requests: list[RecordedRequest] = field(default_factory=list)


@dataclass
class JsonResponse:
    body: dict[str, Any] | list[Any]
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class StreamingResponse:
    chunks: list[str]
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = "text/event-stream"
    delay_s: float = 0.0


@contextmanager
def run_json_server(
    responder: Callable[[str, dict[str, Any]], dict[str, Any] | list[Any] | JsonResponse | StreamingResponse],
) -> Iterator[tuple[str, ServerState]]:
    state = ServerState()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8"))
            state.requests.append(
                RecordedRequest(
                    path=self.path,
                    headers={key: value for key, value in self.headers.items()},
                    body=body,
                )
            )
            payload = responder(self.path, body)
            if isinstance(payload, StreamingResponse):
                self.send_response(payload.status)
                self.send_header("Content-Type", payload.content_type)
                for key, value in payload.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                for chunk in payload.chunks:
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                    if payload.delay_s > 0:
                        time.sleep(payload.delay_s)
                return

            if isinstance(payload, JsonResponse):
                status = payload.status
                headers = payload.headers
                body_payload = payload.body
            else:
                status = 200
                headers = {}
                body_payload = payload

            encoded = json.dumps(body_payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
