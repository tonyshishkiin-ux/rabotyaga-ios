from __future__ import annotations

import argparse
import asyncio
import logging
import os
import threading
from pathlib import Path

from .hermes import HermesGatewayTransport
from .protection import WindowsDPAPIProtector
from .server import BridgeHTTPServer
from .service import GatewayService
from .store import GatewayStore


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise RuntimeError("LOCALAPPDATA is required")
    return Path(base) / "RabotyagaGateway"


def open_store(path: Path | None) -> GatewayStore:
    return GatewayStore(path or default_data_dir() / "gateway.db", WindowsDPAPIProtector())


async def serve(args) -> None:
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("The bridge must bind to loopback; publish it only with Tailscale Serve")
    store = open_store(args.database)
    hermes_home = Path(args.hermes_home or os.environ.get("HERMES_HOME") or Path(os.environ["LOCALAPPDATA"]) / "hermes")
    hermes = HermesGatewayTransport(store, hermes_home)
    service = GatewayService(store, hermes)
    await hermes.start()
    server = BridgeHTTPServer((args.host, args.port), service, asyncio.get_running_loop())
    thread = threading.Thread(target=server.serve_forever, name="rabotyaga-http", daemon=True)
    thread.start()
    logging.info("Rabotyaga gateway listening on http://%s:%s", args.host, args.port)
    try:
        await asyncio.Event().wait()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        await hermes.close()
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rabotyaga iOS local Hermes bridge")
    parser.add_argument("--database", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8787)
    serve_parser.add_argument("--hermes-home")

    pair_parser = subparsers.add_parser("pair")
    pair_parser.add_argument("--name", default="iPhone")
    pair_parser.add_argument("--ttl", type=int, default=600)

    revoke_parser = subparsers.add_parser("revoke")
    revoke_parser.add_argument("device_id")
    subparsers.add_parser("devices")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "serve":
        asyncio.run(serve(args))
        return
    store = open_store(args.database)
    try:
        if args.command == "pair":
            code = store.create_pairing_code(args.name, args.ttl)
            print(f"One-time pairing code (expires in {args.ttl // 60} min): {code}")
        elif args.command == "revoke":
            print("revoked" if store.revoke_device(args.device_id) else "not active")
        elif args.command == "devices":
            for device in store.list_devices():
                state = "revoked" if device["revoked_at"] else "active"
                print(f"{device['id']}  {state}  {device['name']}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
