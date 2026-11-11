# Rabotyaga Hermes Gateway

The bridge is a separate loopback-only component. It attaches to the already
running Hermes authority through Hermes' protected Windows control pipe and
canonical `hermes-gateway-v1` WebSocket. It does not modify Hermes configuration,
sessions owned by other clients, or provider credentials.

## Security boundaries

- The HTTP listener refuses non-loopback binds.
- The Windows listener remains loopback-only. Remote access may use either
  tailnet-only **Tailscale Serve HTTPS** or the dedicated public Caddy route
  documented in `docs/HERMES_INTEGRATION.md`; Hermes itself is never published.
- Pairing uses an eight-digit, one-use, ten-minute code.
- Each device receives a unique revocable secret. The iOS app stores it in
  Keychain; Windows stores the derived signing key encrypted with current-user
  DPAPI.
- Authenticated requests use HMAC-SHA256 over method, path, timestamp, nonce and
  body hash. A five-minute clock window and a nonce ledger reject replay.
- Message `request_id` values are durable and idempotent. A retry cannot turn one
  send into two Hermes admissions.
- The bridge stores only chat projection and pending approvals. It never logs
  request bodies, credentials, Hermes messages or tool results.

## Local commands

From PowerShell in the repository:

```powershell
.\scripts\hermes_gateway.ps1 -Action serve
.\scripts\hermes_gateway.ps1 -Action pair -DeviceName 'iPhone 15 Pro'
.\scripts\hermes_gateway.ps1 -Action devices
.\scripts\hermes_gateway.ps1 -Action revoke -DeviceId '<id>'
```

The default listener is `http://127.0.0.1:8787`. Publishing it through Tailscale
is intentionally a separate operator action described in
`docs/HERMES_INTEGRATION.md`.

## Tests

The bridge uses only the Python standard library plus the installed Hermes
runtime. Unit tests use a fake transport and never contact Hermes:

```powershell
$env:PYTHONPATH = "$PWD\gateway"
python -m unittest discover -s gateway\tests -v
```

`scripts/verify_bridge_roundtrip.py` is an explicit integration probe. It creates
one isolated Hermes chat, sends a harmless fixed prompt through the real local
model and checks that a real terminal response returns.
