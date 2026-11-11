from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from rabotyaga_gateway.auth import (
    AuthenticationError,
    DEVICE_HEADER,
    NONCE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign_request,
    verify_request,
)
from rabotyaga_gateway.protection import PlaintextProtector
from rabotyaga_gateway.store import GatewayStore


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_root = Path(__file__).parent / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.store = GatewayStore(Path(self.temporary.name) / "test.db", PlaintextProtector())
        code = self.store.create_pairing_code("Test iPhone")
        self.device_id, self.secret = self.store.consume_pairing_code(code)
        self.key = hashlib.sha256(self.secret.encode()).digest()

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def headers(self, *, timestamp: int, nonce: str, body: bytes = b"{}") -> dict[str, str]:
        return {
            DEVICE_HEADER: self.device_id,
            TIMESTAMP_HEADER: str(timestamp),
            NONCE_HEADER: nonce,
            SIGNATURE_HEADER: sign_request(
                self.key, "POST", "/v1/chat/messages", timestamp, nonce, body
            ),
        }

    def test_valid_signature_authenticates_device(self) -> None:
        now = int(time.time())
        result = verify_request(
            method="POST",
            path="/v1/chat/messages",
            body=b"{}",
            headers=self.headers(timestamp=now, nonce="nonce-1"),
            key_lookup=self.store.device_key,
            nonces=self.store,
            now=now,
        )
        self.assertEqual(result.device_id, self.device_id)

    def test_replayed_nonce_is_rejected(self) -> None:
        now = int(time.time())
        headers = self.headers(timestamp=now, nonce="same-nonce")
        arguments = dict(
            method="POST",
            path="/v1/chat/messages",
            body=b"{}",
            headers=headers,
            key_lookup=self.store.device_key,
            nonces=self.store,
            now=now,
        )
        verify_request(**arguments)
        with self.assertRaisesRegex(AuthenticationError, "replayed"):
            verify_request(**arguments)

    def test_stale_timestamp_and_tampered_body_are_rejected(self) -> None:
        now = int(time.time())
        with self.assertRaisesRegex(AuthenticationError, "timestamp"):
            verify_request(
                method="POST",
                path="/v1/chat/messages",
                body=b"{}",
                headers=self.headers(timestamp=now - 301, nonce="old"),
                key_lookup=self.store.device_key,
                nonces=self.store,
                now=now,
            )
        with self.assertRaisesRegex(AuthenticationError, "signature"):
            verify_request(
                method="POST",
                path="/v1/chat/messages",
                body=b'{"changed":true}',
                headers=self.headers(timestamp=now, nonce="tampered"),
                key_lookup=self.store.device_key,
                nonces=self.store,
                now=now,
            )

    def test_revoked_device_is_rejected(self) -> None:
        now = int(time.time())
        headers = self.headers(timestamp=now, nonce="after-revoke")
        self.assertTrue(self.store.revoke_device(self.device_id))
        with self.assertRaisesRegex(AuthenticationError, "revoked"):
            verify_request(
                method="POST",
                path="/v1/chat/messages",
                body=b"{}",
                headers=headers,
                key_lookup=self.store.device_key,
                nonces=self.store,
                now=now,
            )


if __name__ == "__main__":
    unittest.main()
