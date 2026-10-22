"""Minimal HTTP API for the runner (standard library only).

    POST /run   Authorization: Bearer <RUNNER_TOKEN>   {"code": ..., "tests": [...], "time_limit_seconds": 3}
    GET  /healthz

Global concurrency is bounded by RUNNER_MAX_CONCURRENCY; excess requests get
503 so the web app can retry later. Per-user concurrency is enforced by the
web app before calling the runner.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .executor import SandboxUnsupported, execute
from .protocol import ProtocolError, parse_request

MAX_BODY_BYTES = 128 * 1024
TOKEN = os.environ.get("RUNNER_TOKEN", "")
SLOTS = threading.BoundedSemaphore(int(os.environ.get("RUNNER_MAX_CONCURRENCY", "4")))
logger = logging.getLogger("runner")


def authorised(header: str, token: str = "") -> bool:
    token = token or TOKEN
    if not token or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].encode(), token.encode())


class Handler(BaseHTTPRequestHandler):
    server_version = "skillforge-runner"
    sys_version = ""

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # never log request bodies
        logger.info("%s %s", self.command, self.path)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(HTTPStatus.OK, {"status": "ok"})
        else:
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/run":
            return self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        if not authorised(self.headers.get("Authorization", "")):
            return self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorised"})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
        try:
            request = parse_request(json.loads(self.rfile.read(length)))
        except (ProtocolError, ValueError) as exc:
            return self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        if not SLOTS.acquire(blocking=False):
            return self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "busy"})
        try:
            result = execute(request)
        except SandboxUnsupported as exc:
            return self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        finally:
            SLOTS.release()
        return self._send(HTTPStatus.OK, result)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not TOKEN:
        raise SystemExit("RUNNER_TOKEN must be set.")
    port = int(os.environ.get("RUNNER_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)  # noqa: S104 - bound inside an isolated network
    logger.info("runner listening on %s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
