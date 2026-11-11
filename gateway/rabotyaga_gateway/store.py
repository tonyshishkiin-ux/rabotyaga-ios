from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .protection import SecretProtector


SCHEMA_VERSION = 1


class StoreError(ValueError):
    pass


class GatewayStore:
    def __init__(self, path: Path, protector: SecretProtector) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._protector = protector
        self._lock = threading.RLock()
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    protected_key BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    revoked_at REAL
                );
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_hash TEXT PRIMARY KEY,
                    device_name TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    consumed_at REAL
                );
                CREATE TABLE IF NOT EXISTS nonces (
                    device_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    PRIMARY KEY (device_id, nonce),
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                );
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    device_id TEXT PRIMARY KEY,
                    hermes_session_id TEXT,
                    status TEXT NOT NULL DEFAULT 'connecting',
                    status_text TEXT,
                    replay_epoch TEXT,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    request_id TEXT,
                    admission_id TEXT,
                    hermes_row_id INTEGER,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(device_id, request_id, role),
                    UNIQUE(device_id, hermes_row_id),
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    prompt_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    execution_generation INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    command TEXT,
                    choices_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                );
                CREATE INDEX IF NOT EXISTS messages_device_time
                    ON messages(device_id, created_at, id);
                CREATE INDEX IF NOT EXISTS approvals_device_status
                    ON approvals(device_id, status, created_at);
                """
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _hash_pairing_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def create_pairing_code(self, device_name: str, ttl_seconds: int = 600) -> str:
        name = device_name.strip()[:80]
        if not name:
            raise StoreError("device name is required")
        code = f"{secrets.randbelow(100_000_000):08d}"
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM pairing_codes WHERE expires_at < ? OR consumed_at IS NOT NULL",
                (time.time(),),
            )
            self._connection.execute(
                "INSERT INTO pairing_codes(code_hash, device_name, expires_at) VALUES(?, ?, ?)",
                (self._hash_pairing_code(code), name, time.time() + ttl_seconds),
            )
        return code

    def consume_pairing_code(self, code: str, requested_name: str | None = None) -> tuple[str, str]:
        now = time.time()
        code_hash = self._hash_pairing_code(code.strip())
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT device_name, expires_at, consumed_at FROM pairing_codes WHERE code_hash = ?",
                (code_hash,),
            ).fetchone()
            if row is None or row["consumed_at"] is not None or row["expires_at"] < now:
                raise StoreError("pairing code is invalid or expired")
            updated = self._connection.execute(
                "UPDATE pairing_codes SET consumed_at = ? WHERE code_hash = ? AND consumed_at IS NULL",
                (now, code_hash),
            )
            if updated.rowcount != 1:
                raise StoreError("pairing code has already been used")

            device_id = str(uuid.uuid4())
            raw_secret = secrets.token_urlsafe(32)
            signing_key = hashlib.sha256(raw_secret.encode("utf-8")).digest()
            name = (requested_name or row["device_name"]).strip()[:80] or row["device_name"]
            self._connection.execute(
                "INSERT INTO devices(id, name, protected_key, created_at) VALUES(?, ?, ?, ?)",
                (device_id, name, self._protector.protect(signing_key), now),
            )
            self._connection.execute(
                "INSERT INTO chat_sessions(device_id, updated_at) VALUES(?, ?)",
                (device_id, now),
            )
        return device_id, raw_secret

    def device_key(self, device_id: str) -> bytes | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT protected_key FROM devices WHERE id = ? AND revoked_at IS NULL",
                (device_id,),
            ).fetchone()
        return None if row is None else self._protector.unprotect(row["protected_key"])

    def claim_nonce(self, device_id: str, nonce: str, timestamp: int) -> bool:
        cutoff = int(time.time()) - 900
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM nonces WHERE timestamp < ?", (cutoff,))
            try:
                self._connection.execute(
                    "INSERT INTO nonces(device_id, nonce, timestamp) VALUES(?, ?, ?)",
                    (device_id, nonce, timestamp),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def revoke_device(self, device_id: str) -> bool:
        with self._lock, self._connection:
            result = self._connection.execute(
                "UPDATE devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (time.time(), device_id),
            )
        return result.rowcount == 1

    def list_devices(self) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, name, created_at, revoked_at FROM devices ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def hermes_session_id(self, device_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT hermes_session_id FROM chat_sessions WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        return None if row is None else row["hermes_session_id"]

    def set_hermes_session(self, device_id: str, session_id: str, snapshot: dict) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE chat_sessions
                   SET hermes_session_id = ?, status = ?, status_text = NULL,
                       replay_epoch = ?, last_sequence = ?, updated_at = ?
                   WHERE device_id = ?""",
                (
                    session_id,
                    "working" if snapshot.get("running") else "ready",
                    snapshot.get("replay_epoch"),
                    int(snapshot.get("last_sequence") or 0),
                    time.time(),
                    device_id,
                ),
            )
        self.hydrate_messages(device_id, snapshot.get("messages") or [])
        self.hydrate_approvals(device_id, snapshot.get("prompts") or [])

    def all_sessions(self) -> list[tuple[str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT device_id, hermes_session_id FROM chat_sessions WHERE hermes_session_id IS NOT NULL"
            ).fetchall()
        return [(row["device_id"], row["hermes_session_id"]) for row in rows]

    def device_for_session(self, session_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT device_id FROM chat_sessions WHERE hermes_session_id = ?",
                (session_id,),
            ).fetchone()
        return None if row is None else row["device_id"]

    def set_status(self, device_id: str, status: str, text: str | None = None) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE chat_sessions SET status = ?, status_text = ?, updated_at = ? WHERE device_id = ?",
                (status, text[:300] if text else None, time.time(), device_id),
            )

    def add_user_message(self, device_id: str, request_id: str, text: str) -> dict:
        now = time.time()
        message_id = str(uuid.uuid4())
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM messages WHERE device_id = ? AND request_id = ? AND role = 'user'",
                (device_id, request_id),
            ).fetchone()
            if existing is not None:
                if existing["text"] != text:
                    raise StoreError("request_id was already used for different content")
                return dict(existing)
            self._connection.execute(
                """INSERT INTO messages
                   (id, device_id, role, text, request_id, status, created_at, updated_at)
                   VALUES(?, ?, 'user', ?, ?, 'queued', ?, ?)""",
                (message_id, device_id, text, request_id, now, now),
            )
        return {
            "id": message_id,
            "device_id": device_id,
            "role": "user",
            "text": text,
            "request_id": request_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
        }

    def mark_admitted(self, device_id: str, request_id: str, receipt: dict) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE messages SET admission_id = ?, status = ?, updated_at = ?
                   WHERE device_id = ? AND request_id = ? AND role = 'user'""",
                (
                    receipt.get("admission_id"),
                    receipt.get("status") or "started",
                    time.time(),
                    device_id,
                    request_id,
                ),
            )
        self.set_status(device_id, "working", "Hermes обрабатывает сообщение")

    def complete_admission(self, device_id: str, admission_id: str | None, payload: dict) -> None:
        text = payload.get("text")
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False) if text is not None else ""
        status = str(payload.get("status") or "complete")
        now = time.time()
        with self._lock, self._connection:
            user = self._connection.execute(
                "SELECT request_id FROM messages WHERE device_id = ? AND admission_id = ? AND role = 'user'",
                (device_id, admission_id),
            ).fetchone()
            request_id = None if user is None else user["request_id"]
            if admission_id:
                self._connection.execute(
                    "UPDATE messages SET status = ?, updated_at = ? WHERE device_id = ? AND admission_id = ? AND role = 'user'",
                    (status, now, device_id, admission_id),
                )
            existing = self._connection.execute(
                "SELECT id FROM messages WHERE device_id = ? AND admission_id = ? AND role = 'assistant'",
                (device_id, admission_id),
            ).fetchone()
            if existing:
                self._connection.execute(
                    "UPDATE messages SET text = ?, status = ?, updated_at = ? WHERE id = ?",
                    (text, status, now, existing["id"]),
                )
            elif text:
                self._connection.execute(
                    """INSERT INTO messages
                       (id, device_id, role, text, request_id, admission_id, status, created_at, updated_at)
                       VALUES(?, ?, 'assistant', ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), device_id, text, request_id, admission_id, status, now, now),
                )
        self.set_status(device_id, "ready" if status == "complete" else "error", payload.get("error"))

    def hydrate_messages(self, device_id: str, messages: list[dict]) -> None:
        now = time.time()
        with self._lock, self._connection:
            for index, message in enumerate(messages):
                role = message.get("role")
                text = message.get("text")
                row_id = message.get("row_id")
                if role not in {"user", "assistant"} or not isinstance(text, str) or not text:
                    continue
                created = float(message.get("timestamp") or now + index / 1000)
                identifier = f"hermes-{row_id}" if row_id is not None else str(uuid.uuid4())
                try:
                    self._connection.execute(
                        """INSERT INTO messages
                           (id, device_id, role, text, hermes_row_id, status, created_at, updated_at)
                           VALUES(?, ?, ?, ?, ?, 'complete', ?, ?)""",
                        (identifier, device_id, role, text, row_id, created, now),
                    )
                except sqlite3.IntegrityError:
                    continue

    def upsert_approval(self, device_id: str, payload: dict) -> None:
        prompt_id = payload.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            return
        title = payload.get("description") or payload.get("question") or "Требуется подтверждение"
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO approvals
                   (prompt_id, device_id, execution_generation, kind, title, command,
                    choices_json, status, created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                   ON CONFLICT(prompt_id) DO UPDATE SET
                     execution_generation=excluded.execution_generation,
                     title=excluded.title, command=excluded.command,
                     choices_json=excluded.choices_json, status='pending', updated_at=excluded.updated_at""",
                (
                    prompt_id,
                    device_id,
                    int(payload.get("execution_generation") or 0),
                    str(payload.get("kind") or "approval"),
                    str(title)[:1000],
                    str(payload.get("command"))[:2000] if payload.get("command") else None,
                    json.dumps(payload.get("choices") or [], ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def hydrate_approvals(self, device_id: str, prompts: list[dict]) -> None:
        for prompt in prompts:
            self.upsert_approval(device_id, prompt)

    def approval(self, device_id: str, prompt_id: str) -> dict | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM approvals WHERE device_id = ? AND prompt_id = ? AND status = 'pending'",
                (device_id, prompt_id),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["choices"] = json.loads(result.pop("choices_json"))
        return result

    def settle_approval(self, device_id: str, prompt_id: str, status: str = "resolved") -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE approvals SET status = ?, updated_at = ? WHERE device_id = ? AND prompt_id = ?",
                (status, time.time(), device_id, prompt_id),
            )

    def chat_state(self, device_id: str) -> dict:
        with self._lock:
            session = self._connection.execute(
                "SELECT hermes_session_id, status, status_text, updated_at FROM chat_sessions WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            messages = self._connection.execute(
                """SELECT id, role, text, request_id, status, created_at
                   FROM messages WHERE device_id = ? ORDER BY created_at, id""",
                (device_id,),
            ).fetchall()
            approvals = self._connection.execute(
                """SELECT prompt_id, kind, title, command, choices_json, created_at
                   FROM approvals WHERE device_id = ? AND status = 'pending' ORDER BY created_at""",
                (device_id,),
            ).fetchall()
        return {
            "session_id": None if session is None else session["hermes_session_id"],
            "status": "connecting" if session is None else session["status"],
            "status_text": None if session is None else session["status_text"],
            "messages": [dict(row) for row in messages],
            "approvals": [
                {**dict(row), "choices": json.loads(row["choices_json"])}
                for row in approvals
            ],
            "updated_at": time.time() if session is None else session["updated_at"],
        }
