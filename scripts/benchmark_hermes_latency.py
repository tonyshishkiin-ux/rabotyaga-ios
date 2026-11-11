"""Measure Rabotyaga latency without printing prompts, replies, or credentials.

The harness compares the canonical local Hermes WebSocket with the public
Rabotyaga HTTPS projection.  It creates disposable sessions/devices, uses only
a read-only file tool probe, and revokes the HTTP device when finished.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from rabotyaga_gateway.protection import WindowsDPAPIProtector  # noqa: E402
from rabotyaga_gateway.store import GatewayStore  # noqa: E402


HERMES_HOME = Path.home() / "AppData" / "Local" / "hermes"
LIVE_STORE = Path.home() / "AppData" / "Local" / "RabotyagaGateway" / "gateway.db"
PUBLIC_GATEWAY = "https://rabotyaga.viralops.ru"


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile_value
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric = {
        key
        for row in rows
        for key, value in row.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    result: dict[str, Any] = {"runs": len(rows)}
    for key in sorted(numeric):
        values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
        if values:
            result[key] = {
                "median": round(statistics.median(values), 2),
                "mean": round(statistics.fmean(values), 2),
                "p90": percentile(values, 0.9),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
            }
    return result


def payload_text(payload: dict[str, Any]) -> str:
    value = payload.get("text") or payload.get("content") or ""
    return value if isinstance(value, str) else ""


@dataclass(frozen=True)
class Probe:
    category: str
    text: str
    expects_tool: bool = False


def probes(run: int) -> list[Probe]:
    safe_file = ROOT / "gateway" / "README.md"
    return [
        Probe("short", f"Тест {run}. Ответь ровно одним словом: Привет."),
        Probe(
            "normal",
            f"Тест {run}. В двух коротких предложениях объясни, почему дневное небо голубое.",
        ),
        Probe(
            "tool",
            (
                "Это безопасный тест производительности. Обязательно один раз используй read_file, "
                f"прочитай только первые 3 строки файла {safe_file}, затем ответь одним предложением, "
                "что чтение завершено. Ничего не изменяй."
            ),
            expects_tool=True,
        ),
    ]


class DirectHermesBenchmark:
    def __init__(self) -> None:
        self.client = None
        self.session_id: str | None = None

    async def __aenter__(self):
        source = HERMES_HOME / "hermes-agent"
        sys.path.insert(0, str(source))
        from hermes_cli.gateway_client import connect_gateway
        from hermes_cli.gateway_runtime import discover_gateway_endpoint

        discovery = discover_gateway_endpoint(HERMES_HOME)
        if discovery.state != "ready" or discovery.endpoint is None:
            raise RuntimeError(f"Hermes gateway is not ready: {discovery.state}")
        self._connection = connect_gateway(endpoint=discovery.endpoint)
        self.client = await self._connection.__aenter__()
        snapshot = await self.client.rpc(
            "session.create",
            request_id=uuid.uuid4().hex,
            source="gui",
            title=f"Rabotyaga latency benchmark {uuid.uuid4().hex[:8]}",
            safe_mode=False,
            yolo=False,
        )
        self.session_id = str(snapshot["stored_session_id"])
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self._connection.__aexit__(exc_type, exc, traceback)

    async def run(self, probe: Probe) -> dict[str, Any]:
        assert self.client is not None and self.session_id is not None
        stats_before = await self.client.rpc("session.stats", session_id=self.session_id)
        submission_id = str(uuid.uuid4())
        started = time.perf_counter()
        receipt = await self.client.rpc(
            "prompt.submit",
            session_id=self.session_id,
            submission_id=submission_id,
            input_id=submission_id,
            text=probe.text,
        )
        admitted = time.perf_counter()
        admission_id = receipt.get("admission_id")
        first_event: float | None = None
        first_delta: float | None = None
        tool_started: dict[str, float] = {}
        tool_durations: list[float] = []
        tool_names: set[str] = set()
        delta_chars = 0
        status_updates = 0
        deadline = started + 300
        while time.perf_counter() < deadline:
            frame = await asyncio.wait_for(self.client.events.get(), timeout=max(0.1, deadline - time.perf_counter()))
            if isinstance(frame, Exception):
                raise frame
            params = frame.get("params") or {}
            if params.get("session_id") != self.session_id:
                continue
            own_admission = params.get("admission_id") or (params.get("payload") or {}).get("admission_id")
            if own_admission not in {None, admission_id}:
                continue
            now = time.perf_counter()
            first_event = first_event or now
            kind = params.get("type")
            payload = params.get("payload") or {}
            if kind == "status.update":
                status_updates += 1
            elif kind == "message.delta":
                first_delta = first_delta or now
                delta_chars += len(payload_text(payload))
            elif kind == "tool.start":
                tool_id = str(payload.get("tool_call_id") or uuid.uuid4().hex)
                tool_started[tool_id] = now
                tool_names.add(str(payload.get("tool_name") or payload.get("name") or "unknown"))
            elif kind == "tool.complete":
                tool_id = str(payload.get("tool_call_id") or "")
                if tool_id in tool_started:
                    tool_durations.append((now - tool_started.pop(tool_id)) * 1000)
            elif kind == "message.complete" and own_admission == admission_id:
                completed = now
                break
        else:
            raise TimeoutError("Hermes benchmark turn did not finish")
        stats_after = await self.client.rpc("session.stats", session_id=self.session_id)
        output_tokens = max(0, int(stats_after.get("output_tokens") or 0) - int(stats_before.get("output_tokens") or 0))
        prompt_tokens = max(0, int(stats_after.get("prompt_tokens") or 0) - int(stats_before.get("prompt_tokens") or 0))
        api_calls = max(0, int(stats_after.get("api_calls") or 0) - int(stats_before.get("api_calls") or 0))
        total_ms = (completed - started) * 1000
        return {
            "category": probe.category,
            "submit_ms": round((admitted - started) * 1000, 2),
            "first_event_ms": round((first_event - started) * 1000, 2) if first_event else None,
            "ttft_ms": round((first_delta - started) * 1000, 2) if first_delta else None,
            "total_ms": round(total_ms, 2),
            "output_tokens": output_tokens,
            "prompt_tokens": prompt_tokens,
            "api_calls": api_calls,
            "effective_tps": round(output_tokens / (total_ms / 1000), 2) if output_tokens and total_ms else None,
            "reported_tps": stats_after.get("tokens_per_s"),
            "context_tokens": stats_after.get("context_tokens"),
            "context_length": stats_after.get("context_length"),
            "cache_read_tokens": max(
                0,
                int(stats_after.get("cache_read_tokens") or 0) - int(stats_before.get("cache_read_tokens") or 0),
            ),
            "tool_calls": len(tool_names),
            "tool_ms": round(sum(tool_durations), 2),
            "saw_expected_tool": (not probe.expects_tool) or bool(tool_names),
            "delta_chars": delta_chars,
            "status_updates": status_updates,
        }


class HTTPSGatewayBenchmark:
    def __init__(self, base_url: str, poll_interval: float = 1.0, stream: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.stream = stream
        self.device_id = ""
        self.secret = ""
        self._stream_task: asyncio.Task | None = None
        self._stream_ready = asyncio.Event()
        self._stream_events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def __aenter__(self):
        store = GatewayStore(LIVE_STORE, WindowsDPAPIProtector())
        try:
            code = store.create_pairing_code("Disposable latency benchmark", ttl_seconds=120)
        finally:
            store.close()
        result, _ = await self._request(
            "/v1/pair",
            "POST",
            {"code": code, "device_name": "Disposable latency benchmark"},
            authenticated=False,
        )
        self.device_id = str(result["device_id"])
        self.secret = str(result["secret"])
        if self.stream:
            self._stream_task = asyncio.create_task(self._consume_stream())
            await asyncio.wait_for(self._stream_ready.wait(), timeout=15)
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        if self.device_id and self.secret:
            try:
                await self._request("/v1/device", "DELETE", None, authenticated=True)
            except Exception:
                pass
        self.secret = ""

    async def _consume_stream(self) -> None:
        path = "/v1/chat/stream"
        headers = {"Accept": "text/event-stream", **self._signed_headers("GET", path, b"")}
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.base_url + path, headers=headers) as response:
                    if response.status != 200:
                        raise RuntimeError(f"stream HTTP {response.status}")
                    data_lines: list[str] = []
                    while True:
                        raw = await response.content.readline()
                        if not raw:
                            return
                        line = raw.decode("utf-8").rstrip("\r\n")
                        if not line:
                            if not data_lines:
                                continue
                            event = json.loads("\n".join(data_lines))
                            data_lines.clear()
                            if event.get("type") == "state":
                                self._stream_ready.set()
                            await self._stream_events.put(event)
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
        finally:
            self._stream_ready.set()

    def _signed_headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        timestamp = int(time.time())
        nonce = str(uuid.uuid4())
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body_hash}".encode()
        derived = hashlib.sha256(self.secret.encode()).digest()
        signature = base64.urlsafe_b64encode(hmac.new(derived, canonical, hashlib.sha256).digest()).rstrip(b"=")
        return {
            "X-Rabotyaga-Device": self.device_id,
            "X-Rabotyaga-Timestamp": str(timestamp),
            "X-Rabotyaga-Nonce": nonce,
            "X-Rabotyaga-Signature": signature.decode(),
        }

    async def _request(
        self,
        path: str,
        method: str,
        payload: dict[str, Any] | None,
        *,
        authenticated: bool,
    ) -> tuple[dict[str, Any], float]:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if authenticated:
            headers.update(self._signed_headers(method, path, body))
        request = urllib.request.Request(
            self.base_url + path,
            data=body if method in {"POST", "PUT", "PATCH"} else None,
            method=method,
            headers=headers,
        )
        started = time.perf_counter()

        def send() -> dict[str, Any]:
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                raise RuntimeError(f"gateway HTTP {error.code}") from error

        result = await asyncio.to_thread(send)
        return result, (time.perf_counter() - started) * 1000

    async def network_samples(self, count: int) -> list[float]:
        values = []
        for _ in range(count):
            _, elapsed = await self._request("/v1/chat", "GET", None, authenticated=True)
            values.append(round(elapsed, 2))
        return values

    async def run(self, probe: Probe) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        before, initial_state_ms = await self._request("/v1/chat", "GET", None, authenticated=True)
        existing = {message["id"] for message in before.get("messages", [])}
        while not self._stream_events.empty():
            self._stream_events.get_nowait()
        started = time.perf_counter()
        _, submit_ms = await self._request(
            "/v1/chat/messages",
            "POST",
            {"request_id": request_id, "text": probe.text},
            authenticated=True,
        )
        first_visible: float | None = None
        complete: float | None = None
        poll_latency: list[float] = []
        poll_count = 0
        deadline = started + 300
        while time.perf_counter() < deadline and self.stream:
            event = await asyncio.wait_for(
                self._stream_events.get(), timeout=max(0.1, deadline - time.perf_counter())
            )
            if event.get("type") != "message":
                continue
            assistant = event.get("message") or {}
            if assistant.get("role") != "assistant" or assistant.get("request_id") != request_id:
                continue
            now = time.perf_counter()
            if assistant.get("text"):
                first_visible = first_visible or now
            if assistant.get("status") in {"complete", "failed"}:
                complete = now
                break
        while time.perf_counter() < deadline and not self.stream:
            await asyncio.sleep(self.poll_interval)
            state, elapsed = await self._request("/v1/chat", "GET", None, authenticated=True)
            poll_latency.append(elapsed)
            poll_count += 1
            assistant = next(
                (
                    message
                    for message in state.get("messages", [])
                    if message.get("role") == "assistant"
                    and message.get("request_id") == request_id
                    and message.get("id") not in existing
                ),
                None,
            )
            now = time.perf_counter()
            if assistant and assistant.get("text"):
                first_visible = first_visible or now
                if assistant.get("status") in {"complete", "failed"}:
                    complete = now
                    break
            if state.get("status") == "error":
                raise RuntimeError("gateway reported a failed benchmark turn")
        if complete is None:
            raise TimeoutError("public gateway benchmark turn did not finish")
        return {
            "category": probe.category,
            "initial_state_ms": round(initial_state_ms, 2),
            "submit_ms": round(submit_ms, 2),
            "first_visible_ms": round((first_visible - started) * 1000, 2) if first_visible else None,
            "total_ms": round((complete - started) * 1000, 2),
            "poll_count": poll_count,
            "poll_rtt_ms": round(statistics.fmean(poll_latency), 2) if poll_latency else None,
            "poll_interval_ms": round(self.poll_interval * 1000, 2),
            "transport": "sse" if self.stream else "polling",
        }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--public-url", default=PUBLIC_GATEWAY)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be positive")
    output = args.output or ROOT / "artifacts" / "benchmarks" / f"baseline-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    direct_rows: list[dict[str, Any]] = []
    public_rows: list[dict[str, Any]] = []
    print("direct:start", file=sys.stderr, flush=True)
    async with DirectHermesBenchmark() as direct:
        for run in range(1, args.runs + 1):
            for probe in probes(run):
                print(f"direct:{probe.category}:{run}", file=sys.stderr, flush=True)
                direct_rows.append(await direct.run(probe))

    print("public:start", file=sys.stderr, flush=True)
    async with HTTPSGatewayBenchmark(args.public_url, args.poll_interval, args.stream) as public:
        network_rtt = await public.network_samples(args.runs)
        for run in range(1, args.runs + 1):
            for probe in probes(run):
                print(f"public:{probe.category}:{run}", file=sys.stderr, flush=True)
                public_rows.append(await public.run(probe))

    report = {
        "schema": 1,
        "created_at": time.time(),
        "runs_per_category": args.runs,
        "poll_interval_ms": args.poll_interval * 1000,
        "direct": {
            "rows": direct_rows,
            "categories": {
                category: aggregate([row for row in direct_rows if row["category"] == category])
                for category in ("short", "normal", "tool")
            },
        },
        "public": {
            "network_rtt_ms": network_rtt,
            "network_summary": aggregate([{"rtt_ms": value} for value in network_rtt]),
            "rows": public_rows,
            "categories": {
                category: aggregate([row for row in public_rows if row["category"] == category])
                for category in ("short", "normal", "tool")
            },
        },
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    asyncio.run(main())
