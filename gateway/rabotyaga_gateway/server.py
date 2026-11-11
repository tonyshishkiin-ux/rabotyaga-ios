from __future__ import annotations

import asyncio
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .auth import AuthenticationError, verify_request
from .hermes import HermesUnavailable
from .service import GatewayService
from .store import StoreError


logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service: GatewayService, loop: asyncio.AbstractEventLoop):
        super().__init__(address, BridgeHandler)
        self.service = service
        self.event_loop = loop


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        logger.info("HTTP %s", format % args)

    def _body(self) -> bytes:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise StoreError("invalid content length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise StoreError("request body is too large")
        return self.rfile.read(length)

    @staticmethod
    def _json(body: bytes) -> dict:
        try:
            value = json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StoreError("request body is not valid JSON") from exc
        if not isinstance(value, dict):
            raise StoreError("request body must be an object")
        return value

    def _authenticate(self, body: bytes) -> str:
        device = verify_request(
            method=self.command,
            path=self.path,
            body=body,
            headers=self.headers,
            key_lookup=self.server.service.store.device_key,
            nonces=self.server.service.store,
        )
        return device.device_id

    def _await(self, coroutine):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.server.event_loop)
        return future.result(timeout=30)

    def _send(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self) -> None:
        body = self._body()
        path = urlsplit(self.path).path
        service = self.server.service

        if self.command == "GET" and path == "/v1/health":
            self._send(HTTPStatus.OK, {"ok": True, "service": "rabotyaga-gateway"})
            return
        if self.command == "POST" and path == "/v1/pair":
            payload = self._json(body)
            result = service.pair(str(payload.get("code") or ""), str(payload.get("device_name") or "iPhone"))
            self._send(HTTPStatus.CREATED, result)
            return

        device_id = self._authenticate(body)
        if self.command == "GET" and path == "/v1/chat":
            self._send(HTTPStatus.OK, self._await(service.state(device_id)))
            return
        if self.command == "POST" and path == "/v1/chat/messages":
            self._send(HTTPStatus.ACCEPTED, self._await(service.submit(device_id, self._json(body))))
            return
        if self.command == "POST" and path.startswith("/v1/chat/approvals/"):
            prompt_id = path.removeprefix("/v1/chat/approvals/")
            if not prompt_id or "/" in prompt_id:
                raise StoreError("approval id is invalid")
            self._send(HTTPStatus.OK, self._await(service.approve(device_id, prompt_id, self._json(body))))
            return
        if self.command == "DELETE" and path == "/v1/device":
            self._send(HTTPStatus.OK, service.revoke(device_id))
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _handle(self) -> None:
        try:
            self._dispatch()
        except AuthenticationError as exc:
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized", "message": str(exc)})
        except StoreError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": str(exc)})
        except HermesUnavailable:
            self._send(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "hermes_unavailable", "message": "Hermes временно недоступен"},
            )
        except TimeoutError:
            self._send(HTTPStatus.GATEWAY_TIMEOUT, {"error": "timeout", "message": "Hermes не ответил вовремя"})
        except Exception as exc:
            logger.exception("Unhandled bridge request error: %s", type(exc).__name__)
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})

    do_GET = _handle
    do_POST = _handle
    do_DELETE = _handle
