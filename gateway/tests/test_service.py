from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from rabotyaga_gateway.protection import PlaintextProtector
from rabotyaga_gateway.service import GatewayService
from rabotyaga_gateway.store import GatewayStore, StoreError


class FakeHermes:
    def __init__(self, store: GatewayStore) -> None:
        self.store = store
        self.submissions = []
        self.session_id = "test-hermes-session"

    async def ensure_session(self, device_id: str) -> str:
        if self.store.hermes_session_id(device_id) is None:
            self.store.set_hermes_session(
                device_id,
                self.session_id,
                {
                    "stored_session_id": self.session_id,
                    "running": False,
                    "replay_epoch": "test-epoch",
                    "last_sequence": 0,
                    "messages": [],
                    "prompts": [],
                },
            )
        return self.session_id

    async def submit(self, device_id: str, request_id: str, text: str) -> dict:
        await self.ensure_session(device_id)
        self.store.add_user_message(device_id, request_id, text)
        receipt = {"admission_id": f"admission-{request_id}", "status": "started"}
        self.store.mark_admitted(device_id, request_id, receipt)
        self.submissions.append((request_id, text))
        return receipt

    async def approve(self, device_id: str, prompt_id: str, choice: str) -> dict:
        approval = self.store.approval(device_id, prompt_id)
        if approval is None or choice not in approval["choices"]:
            raise ValueError("invalid approval")
        self.store.settle_approval(device_id, prompt_id)
        return {"status": "resolved"}


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temporary_root = Path(__file__).parent / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.store = GatewayStore(Path(self.temporary.name) / "test.db", PlaintextProtector())
        code = self.store.create_pairing_code("Test iPhone")
        self.device_id, _ = self.store.consume_pairing_code(code)
        self.hermes = FakeHermes(self.store)
        self.service = GatewayService(self.store, self.hermes)

    async def asyncTearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    async def test_duplicate_request_id_is_idempotent(self) -> None:
        payload = {"request_id": "12345678-1234-1234-1234-123456789abc", "text": "Привет"}
        first = await self.service.submit(self.device_id, payload)
        second = await self.service.submit(self.device_id, payload)
        self.assertEqual(first["admission_id"], second["admission_id"])
        state = self.store.chat_state(self.device_id)
        self.assertEqual(len(state["messages"]), 1)

    async def test_request_id_cannot_be_reused_for_different_text(self) -> None:
        request_id = "12345678-1234-1234-1234-123456789abc"
        await self.service.submit(self.device_id, {"request_id": request_id, "text": "Первое"})
        with self.assertRaises(StoreError):
            await self.service.submit(self.device_id, {"request_id": request_id, "text": "Другое"})

    async def test_completion_and_recovery_are_visible_in_state(self) -> None:
        request_id = "12345678-1234-1234-1234-123456789abc"
        result = await self.service.submit(
            self.device_id, {"request_id": request_id, "text": "Ответь коротко"}
        )
        self.store.complete_admission(
            self.device_id,
            result["admission_id"],
            {"text": "Настоящий ответ Hermes", "status": "complete"},
        )
        state = await self.service.state(self.device_id)
        self.assertEqual([row["role"] for row in state["messages"]], ["user", "assistant"])
        self.assertEqual(state["messages"][-1]["text"], "Настоящий ответ Hermes")
        self.assertEqual(state["status"], "ready")

    async def test_approval_is_scoped_to_projected_choice(self) -> None:
        await self.hermes.ensure_session(self.device_id)
        self.store.upsert_approval(
            self.device_id,
            {
                "prompt_id": "prompt-1",
                "execution_generation": 7,
                "kind": "approval",
                "description": "Отправить сообщение клиенту?",
                "command": "send --draft 42",
                "choices": ["approve", "deny"],
            },
        )
        result = await self.service.approve(
            self.device_id,
            "prompt-1",
            {"request_id": "12345678-1234-1234-1234-123456789abc", "choice": "deny"},
        )
        self.assertEqual(result["status"], "resolved")
        with self.assertRaises(ValueError):
            await self.hermes.approve(self.device_id, "prompt-1", "approve forever")


if __name__ == "__main__":
    unittest.main()
