from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Protocol

from .store import GatewayStore


logger = logging.getLogger(__name__)


class HermesUnavailable(RuntimeError):
    pass


class HermesTransport(Protocol):
    async def ensure_session(self, device_id: str) -> str: ...
    async def submit(self, device_id: str, request_id: str, text: str) -> dict: ...
    async def approve(self, device_id: str, prompt_id: str, choice: str) -> dict: ...


class HermesGatewayTransport:
    """Attach to the installed Hermes authority without starting or reconfiguring it."""

    def __init__(self, store: GatewayStore, hermes_home: Path) -> None:
        self.store = store
        self.hermes_home = hermes_home
        self._client = None
        self._connected = asyncio.Event()
        self._stop = asyncio.Event()
        self._runner: asyncio.Task | None = None
        self._create_locks: dict[str, asyncio.Lock] = {}

    def _load_client_api(self):
        source = self.hermes_home / "hermes-agent"
        if not source.is_dir():
            raise HermesUnavailable(f"Hermes source directory is missing: {source}")
        source_text = str(source)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        os.environ.setdefault("HERMES_HOME", str(self.hermes_home))
        from hermes_cli.gateway_client import connect_gateway
        from hermes_cli.gateway_runtime import discover_gateway_endpoint

        return connect_gateway, discover_gateway_endpoint

    async def start(self) -> None:
        if self._runner is None:
            self._runner = asyncio.create_task(self._connection_loop())

    async def close(self) -> None:
        self._stop.set()
        if self._runner is not None:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass

    async def wait_ready(self, timeout: float = 15) -> None:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
        except TimeoutError as exc:
            raise HermesUnavailable("Hermes gateway is not reachable") from exc

    async def _connection_loop(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                connect_gateway, discover = self._load_client_api()
                discovery = await asyncio.to_thread(discover, self.hermes_home)
                if discovery.state != "ready" or discovery.endpoint is None:
                    raise HermesUnavailable(f"Hermes gateway state is {discovery.state}")
                async with connect_gateway(endpoint=discovery.endpoint) as client:
                    self._client = client
                    self._connected.set()
                    delay = 1.0
                    await self._reattach_sessions()
                    await self._consume_events(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Hermes gateway disconnected: %s", type(exc).__name__)
            finally:
                self._client = None
                self._connected.clear()
                for device_id, _ in self.store.all_sessions():
                    self.store.set_status(device_id, "offline", "Соединение с Hermes восстанавливается")
            try:
                await asyncio.wait_for(self._stop.wait(), delay)
            except TimeoutError:
                delay = min(delay * 2, 15)

    async def _reattach_sessions(self) -> None:
        for device_id, session_id in self.store.all_sessions():
            try:
                snapshot = await self._rpc("session.resume", session_id=session_id)
                self.store.set_hermes_session(device_id, snapshot["stored_session_id"], snapshot)
            except Exception as exc:
                logger.warning("Could not resume one Rabotyaga session: %s", type(exc).__name__)
                self.store.set_status(device_id, "error", "Не удалось восстановить сессию Hermes")

    async def _consume_events(self, client) -> None:
        while not self._stop.is_set():
            frame = await client.events.get()
            if isinstance(frame, Exception):
                raise frame
            params = frame.get("params") or {}
            event_type = params.get("type")
            session_id = params.get("session_id")
            if not isinstance(event_type, str) or not isinstance(session_id, str):
                continue
            device_id = self.store.device_for_session(session_id)
            if device_id is None:
                continue
            payload = params.get("payload") or {}
            admission_id = params.get("admission_id") or payload.get("admission_id")
            if event_type == "message.complete":
                self.store.complete_admission(device_id, admission_id, payload)
            elif event_type == "status.update":
                self.store.set_status(device_id, "working", str(payload.get("text") or ""))
            elif event_type in {"tool.start", "tool.generating"}:
                name = payload.get("name") or "инструмент"
                self.store.set_status(device_id, "working", f"Hermes использует: {name}")
            elif event_type == "approval.request":
                self.store.upsert_approval(
                    device_id,
                    {
                        **payload,
                        "kind": "approval",
                        "execution_generation": params.get("execution_generation"),
                    },
                )
                self.store.set_status(device_id, "waiting", "Hermes ждёт подтверждения")
            elif event_type == "clarify.request":
                self.store.upsert_approval(
                    device_id,
                    {
                        **payload,
                        "kind": "clarify",
                        "execution_generation": params.get("execution_generation"),
                    },
                )
                self.store.set_status(device_id, "waiting", "Hermes задал уточняющий вопрос")
            elif event_type in {"approval.settled", "clarify.settled"}:
                prompt_id = payload.get("prompt_id")
                if isinstance(prompt_id, str):
                    self.store.settle_approval(device_id, prompt_id)
            elif event_type == "error":
                self.store.set_status(device_id, "error", str(payload.get("message") or "Ошибка Hermes"))

    async def _rpc(self, method: str, **params):
        await self.wait_ready()
        client = self._client
        if client is None:
            raise HermesUnavailable("Hermes gateway disconnected")
        return await client.rpc(method, **params)

    async def ensure_session(self, device_id: str) -> str:
        await self.start()
        existing = self.store.hermes_session_id(device_id)
        if existing:
            return existing
        lock = self._create_locks.setdefault(device_id, asyncio.Lock())
        async with lock:
            existing = self.store.hermes_session_id(device_id)
            if existing:
                return existing
            request_id = uuid.uuid4().hex
            snapshot = await self._rpc(
                "session.create",
                request_id=request_id,
                source="gui",
                title="Работяга iOS",
                safe_mode=False,
                yolo=False,
            )
            session_id = snapshot["stored_session_id"]
            self.store.set_hermes_session(device_id, session_id, snapshot)
            return session_id

    async def submit(self, device_id: str, request_id: str, text: str) -> dict:
        session_id = await self.ensure_session(device_id)
        self.store.add_user_message(device_id, request_id, text)
        try:
            receipt = await self._rpc(
                "prompt.submit",
                session_id=session_id,
                submission_id=request_id,
                input_id=request_id,
                text=text,
            )
        except Exception:
            self.store.set_status(device_id, "offline", "Отправка не подтверждена; повторите запрос")
            raise
        self.store.mark_admitted(device_id, request_id, receipt)
        return receipt

    async def approve(self, device_id: str, prompt_id: str, choice: str) -> dict:
        session_id = await self.ensure_session(device_id)
        approval = self.store.approval(device_id, prompt_id)
        if approval is None:
            raise ValueError("approval is no longer pending")
        if choice not in approval["choices"]:
            raise ValueError("choice is not allowed for this approval")
        method = "approval.respond" if approval["kind"] == "approval" else "clarify.respond"
        params = {
            "session_id": session_id,
            "execution_generation": approval["execution_generation"],
            "prompt_id": prompt_id,
        }
        params["choice" if method == "approval.respond" else "answer"] = choice
        result = await self._rpc(method, **params)
        self.store.settle_approval(device_id, prompt_id)
        self.store.set_status(device_id, "working", "Hermes продолжает выполнение")
        return result
