from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Mapping, Protocol


DEVICE_HEADER = "X-Rabotyaga-Device"
TIMESTAMP_HEADER = "X-Rabotyaga-Timestamp"
NONCE_HEADER = "X-Rabotyaga-Nonce"
SIGNATURE_HEADER = "X-Rabotyaga-Signature"
MAX_CLOCK_SKEW_SECONDS = 300


class NonceStore(Protocol):
    def claim_nonce(self, device_id: str, nonce: str, timestamp: int) -> bool: ...


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthenticatedDevice:
    device_id: str


def body_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_request(
    method: str, path: str, timestamp: int, nonce: str, body: bytes
) -> bytes:
    return (
        f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_digest(body)}"
    ).encode("utf-8")


def sign_request(
    key: bytes, method: str, path: str, timestamp: int, nonce: str, body: bytes
) -> str:
    signature = hmac.new(
        key,
        canonical_request(method, path, timestamp, nonce, body),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def verify_request(
    *,
    method: str,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
    key_lookup,
    nonces: NonceStore,
    now: int | None = None,
) -> AuthenticatedDevice:
    device_id = headers.get(DEVICE_HEADER, "").strip()
    nonce = headers.get(NONCE_HEADER, "").strip()
    supplied = headers.get(SIGNATURE_HEADER, "").strip()
    raw_timestamp = headers.get(TIMESTAMP_HEADER, "").strip()

    if not device_id or not nonce or not supplied or not raw_timestamp:
        raise AuthenticationError("missing authentication headers")
    if len(device_id) > 128 or len(nonce) > 128:
        raise AuthenticationError("invalid authentication headers")
    try:
        timestamp = int(raw_timestamp)
    except ValueError as exc:
        raise AuthenticationError("invalid timestamp") from exc

    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > MAX_CLOCK_SKEW_SECONDS:
        raise AuthenticationError("request timestamp is outside the allowed window")

    key = key_lookup(device_id)
    if key is None:
        raise AuthenticationError("unknown or revoked device")
    expected = sign_request(key, method, path, timestamp, nonce, body)
    if not hmac.compare_digest(supplied, expected):
        raise AuthenticationError("invalid signature")
    if not nonces.claim_nonce(device_id, nonce, timestamp):
        raise AuthenticationError("replayed request")
    return AuthenticatedDevice(device_id=device_id)
