"""One disposable real round-trip through the installed Hermes authority.

The script prints only a boolean result and response length. It never prints
credentials, endpoint metadata, existing sessions, or transcript content.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from rabotyaga_gateway.hermes import HermesGatewayTransport  # noqa: E402
from rabotyaga_gateway.protection import PlaintextProtector  # noqa: E402
from rabotyaga_gateway.store import GatewayStore  # noqa: E402


async def main() -> None:
    temporary = ROOT / "gateway" / "tests" / ".tmp" / "real-roundtrip"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    store = GatewayStore(temporary / "gateway.db", PlaintextProtector())
    hermes_home = Path.home() / "AppData" / "Local" / "hermes"
    transport = HermesGatewayTransport(store, hermes_home)
    try:
        code = store.create_pairing_code("Round-trip test")
        device_id, _ = store.consume_pairing_code(code)
        await transport.start()
        await transport.wait_ready(15)
        request_id = str(uuid.uuid4())
        await transport.submit(
            device_id,
            request_id,
            "Ответь ровно двумя словами: СВЯЗЬ УСТАНОВЛЕНА",
        )
        deadline = asyncio.get_running_loop().time() + 120
        while asyncio.get_running_loop().time() < deadline:
            state = store.chat_state(device_id)
            replies = [row for row in state["messages"] if row["role"] == "assistant"]
            if replies:
                text = replies[-1]["text"].strip().upper()
                verified = "СВЯЗЬ" in text and "УСТАНОВЛЕНА" in text
                print(f"real_response_verified={str(verified).lower()} length={len(text)}")
                if not verified:
                    raise RuntimeError("Hermes returned a response that did not match the safe probe")
                return
            if state["status"] == "error":
                raise RuntimeError("Hermes reported an error during the probe")
            await asyncio.sleep(0.5)
        raise TimeoutError("Hermes did not complete the probe within 120 seconds")
    finally:
        await transport.close()
        store.close()
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
