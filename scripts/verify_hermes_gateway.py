"""Read-only smoke check for the locally installed Hermes gateway.

This script deliberately prints only protocol metadata and aggregate counts. It
does not print session titles, messages, credentials, or endpoint identifiers.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from hermes_cli.gateway_client import connect_gateway
from hermes_cli.gateway_runtime import discover_gateway_endpoint


async def main() -> None:
    hermes_home = Path.home() / "AppData" / "Local" / "hermes"
    print("discovering", file=sys.stderr, flush=True)
    discovery = discover_gateway_endpoint(hermes_home)
    if discovery.state != "ready" or discovery.endpoint is None:
        raise RuntimeError(f"Hermes gateway is not ready: {discovery.state}")

    print("connecting", file=sys.stderr, flush=True)
    async with asyncio.timeout(15):
        async with connect_gateway(endpoint=discovery.endpoint) as client:
            print("connected", file=sys.stderr, flush=True)
            result = await client.rpc(
                "session.list",
                _timeout=10,
                scope="live",
                limit=5,
                include_hidden=False,
            )

    print(
        json.dumps(
            {
                "state": discovery.state,
                "capabilities": sorted(discovery.endpoint.capabilities),
                "scope": result.get("scope"),
                "session_count": len(result.get("sessions", [])),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
