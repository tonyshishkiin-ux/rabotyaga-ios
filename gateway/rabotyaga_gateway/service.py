from __future__ import annotations

import re
from dataclasses import dataclass

from .hermes import HermesTransport
from .store import GatewayStore, StoreError


REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{16,80}$")


@dataclass
class GatewayService:
    store: GatewayStore
    hermes: HermesTransport

    def pair(self, code: str, device_name: str) -> dict:
        device_id, secret = self.store.consume_pairing_code(code, device_name)
        return {"device_id": device_id, "secret": secret, "algorithm": "HMAC-SHA256"}

    async def state(self, device_id: str) -> dict:
        await self.hermes.ensure_session(device_id)
        return self.store.chat_state(device_id)

    async def submit(self, device_id: str, payload: dict) -> dict:
        request_id = str(payload.get("request_id") or "")
        text = str(payload.get("text") or "").strip()
        if not REQUEST_ID.fullmatch(request_id):
            raise StoreError("request_id is invalid")
        if not text or len(text) > 20_000:
            raise StoreError("message must contain 1 to 20000 characters")
        receipt = await self.hermes.submit(device_id, request_id, text)
        return {
            "request_id": request_id,
            "admission_id": receipt.get("admission_id"),
            "status": receipt.get("status") or "accepted",
        }

    async def approve(self, device_id: str, prompt_id: str, payload: dict) -> dict:
        request_id = str(payload.get("request_id") or "")
        choice = str(payload.get("choice") or "")
        if not REQUEST_ID.fullmatch(request_id) or not choice:
            raise StoreError("approval request is invalid")
        result = await self.hermes.approve(device_id, prompt_id, choice)
        return {"request_id": request_id, "status": result.get("status", "resolved")}

    def revoke(self, device_id: str) -> dict:
        if not self.store.revoke_device(device_id):
            raise StoreError("device is already revoked")
        return {"revoked": True}
