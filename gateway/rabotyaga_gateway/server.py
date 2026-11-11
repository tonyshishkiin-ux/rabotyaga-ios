from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .auth import AuthenticationError, verify_request
from .hermes import HermesUnavailable
from .rate_limit import RateLimit, RateLimitExceeded, SlidingWindowLimiter
from .service import GatewayService
from .store import StoreError


logger = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024
MAX_CONCURRENT_REQUESTS = 32
CLIENT_IP_HEADER = "X-Rabotyaga-Client-IP"


class RequestTimeout(RuntimeError):
    pass


class PayloadTooLarge(StoreError):
    pass


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, service: GatewayService, loop: asyncio.AbstractEventLoop):
        super().__init__(address, BridgeHandler)
        self.service = service
        self.event_loop = loop
        self.rate_limiter = SlidingWindowLimiter()
        self._request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

    def process_request(self, request, client_address) -> None:
        if not self._request_slots.acquire(blocking=False):
            try:
                body = b'{"error":"busy","message":"Gateway is temporarily busy"}'
                response = (
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Type: application/json; charset=utf-8\r\n"
                    b"Cache-Control: no-store\r\n"
                    b"Connection: close\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                    + body
                )
                request.sendall(response)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeHTTPServer
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format: str, *args) -> None:
        # Do not copy request paths, headers or message bodies into service logs.
        logger.debug("Rabotyaga HTTP response completed")

    def _source_key(self) -> str:
        candidate = self.headers.get(CLIENT_IP_HEADER, "").strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            return str(ipaddress.ip_address(self.client_address[0]))

    def _limit_public_request(self, path: str) -> None:
        source = self._source_key()
        limits = [
            RateLimit("global", "all", 300, 60),
            RateLimit("source", source, 120, 60),
        ]
        if path == "/v1/pair":
            limits.extend(
                [
                    RateLimit("pair-global", "all", 30, 60),
                    RateLimit("pair-source", source, 5, 60),
                    RateLimit("pair-source-hour", source, 20, 3600),
                ]
            )
        self.server.rate_limiter.check(limits)

    def _limit_device_request(self, device_id: str, path: str) -> None:
        limits = [RateLimit("device", device_id, 120, 60)]
        if path == "/v1/chat/messages":
            limits.extend(
                [
                    RateLimit("submit", device_id, 10, 60),
                    RateLimit("submit-hour", device_id, 60, 3600),
                ]
            )
        elif path.startswith("/v1/chat/approvals/"):
            limits.append(RateLimit("approval", device_id, 12, 60))
        elif path == "/v1/device":
            limits.append(RateLimit("revoke", device_id, 5, 60))
        self.server.rate_limiter.check(limits)

    def _body(self) -> bytes:
        if self.headers.get("Transfer-Encoding"):
            raise StoreError("transfer encoding is not supported")
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise StoreError("invalid content length") from exc
        if length < 0:
            raise StoreError("invalid content length")
        if length > MAX_BODY_BYTES:
            raise PayloadTooLarge("request body is too large")
        try:
            return self.rfile.read(length)
        except TimeoutError as exc:
            raise RequestTimeout("request body timed out") from exc

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

    def _send(self, status: HTTPStatus, payload: dict, *, retry_after: int | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self) -> None:
        path = urlsplit(self.path).path
        self._limit_public_request(path)
        body = self._body()
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
        self._limit_device_request(device_id, path)
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
        except AuthenticationError:
            self._send(
                HTTPStatus.UNAUTHORIZED,
                {"error": "unauthorized", "message": "Authentication failed"},
            )
        except RateLimitExceeded as exc:
            self._send(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": "rate_limited", "message": "Too many requests"},
                retry_after=exc.retry_after,
            )
        except RequestTimeout:
            self._send(HTTPStatus.REQUEST_TIMEOUT, {"error": "request_timeout"})
        except PayloadTooLarge:
            self._send(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": "payload_too_large", "message": "Request body is too large"},
            )
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
