# Hermes integration for Работяга iOS 1.4

## Confirmed local interfaces

The installed Hermes Agent is version 0.22.7 at commit
`b200f5bc60e31588ba2cb60e288029c4a54ba5fa`. Its active gateway exposes the
canonical JSON-RPC 2.0 protocol over loopback WebSocket `/api/ws`, negotiated as
`hermes-gateway-v1`.

The protected Windows named pipe is the authentication boundary. A same-user
local process discovers a credential-free endpoint and mints a short-lived,
single-use session ticket. The bridge uses that official client path; an iPhone
never receives a Hermes ticket or direct Hermes endpoint.

Confirmed canonical capabilities:

- `session-authority-v1` for isolated durable chat sessions;
- `durable-admission-v1` for idempotent prompt admission;
- `event-replay-v1` for reconnect recovery;
- `session.create` / `session.resume` and persisted transcript snapshots;
- `prompt.submit`, streamed `message.delta`, terminal `message.complete`;
- `status.update` and tool lifecycle events for long tasks;
- generation-scoped `approval.respond` and `clarify.respond`.

## Network and trust architecture

```text
iPhone app
  Public HTTPS + per-device HMAC (no phone VPN)
      ↓
Ubuntu Caddy: exact API allowlist, body/time limits, no diagnostics
      ↓ existing private Tailscale HTTPS channel
Windows Tailscale Serve (tailnet only, no Funnel)
      ↓
127.0.0.1:8787 Rabotyaga Gateway
  DPAPI device keys, replay/idempotency ledger, rate limits, local chat projection
      ↓
Hermes protected named pipe → one-use ticket → loopback WebSocket
      ↓
Existing Hermes session, local Qwen and configured tools
```

For the original 1.2 route, Tailscale is the encrypted network boundary; the per-device key is an additional
application boundary. A tailnet member without a valid device key cannot submit
messages. Revocation sets the device inactive immediately, independently of
Tailscale membership.

## Public mobile route in 1.3

Version 1.3 adds a dedicated HTTPS edge at `rabotyaga.viralops.ru` so the iPhone
does not need a VPN. The existing Ubuntu Caddy instance accepts only the exact
mobile API paths, limits request bodies and upstream timeouts, and forwards over
the existing private Tailscale HTTPS path to the loopback-only Windows bridge.
The public edge does not expose the health endpoint, Hermes WebSocket,
administration, diagnostics or any other Caddy site.

Every protected request still uses the per-device HMAC, timestamp and one-use
nonce. Pairing codes remain one-use and short-lived. The bridge adds bounded
concurrency plus separate global, source, pairing, device, message, approval and
revocation rate limits. Device keys remain encrypted with Windows DPAPI and in
iOS Keychain. Approval choices remain scoped and are validated by Hermes; a
chat message is never treated as standing approval for later actions.

## API v1

`POST /v1/pair` is the only unauthenticated mutation. It accepts a one-use code
over HTTPS and returns one device credential. All other routes require the four
`X-Rabotyaga-*` HMAC headers.

- `GET /v1/chat` — durable message projection, task status, pending approvals;
- `GET /v1/chat/stream` — authenticated SSE stream of real Hermes deltas, tool
  states, approvals and reconnect snapshots;
- `POST /v1/chat/messages` — idempotent submission with client `request_id`;
- `POST /v1/chat/approvals/{prompt_id}` — one explicit choice for one projected
  prompt and execution generation;
- `DELETE /v1/device` — revoke the current device;
- `GET /v1/health` — minimal private liveness, no Hermes or identity metadata;
  the public Caddy route deliberately returns 404 for it.

No endpoint can enable YOLO mode, set global approval policy, expose credentials,
or execute an arbitrary RPC method. Missing user input never becomes approval.

## Reconnect and long tasks

Hermes owns the canonical transcript and task lifetime. Every active device has
its own Hermes session; legacy shared mappings are rotated automatically so one
device cannot receive another device's events or inflate its context. The bridge
keeps a durable projection and publishes the canonical `message.delta` events as
authenticated SSE without synthesizing a typing animation. On reconnect it
resumes only the device's mapped Hermes session, hydrates the durable transcript,
pending admissions and pending prompts, then continues consuming events. Client
retries reuse the original `request_id`; Hermes' admission ledger and the bridge
database both reject duplicate work.

The iOS app caches rendered messages under iOS Data Protection and restores them
immediately after relaunch. Key material remains in Keychain. While a turn is
running, one long-lived SSE request replaces one-second polling and displays
`Думает`, `Выполняет инструмент`, `Пишет ответ` and `Ожидает подтверждения` from
real server state. Backgrounding does not cancel the Hermes turn; reconnecting
receives a full state snapshot before new events.

## Private Windows publication

The safe publication command is deliberately not run automatically:

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:8787
tailscale serve status
```

Do not use `tailscale funnel`, a Windows router port forwarding rule or
`0.0.0.0`. The public DNS record terminates only at Ubuntu Caddy; Windows and the
Hermes WebSocket stay private. Before changing Serve, preserve its current
configuration because it may contain unrelated routes.

## Device enrollment

1. Start the bridge in a foreground PowerShell window.
2. After the private Serve route and public Caddy edge are healthy, create a
   one-time pairing code:
   `.\scripts\hermes_gateway.ps1 -Action pair -DeviceName 'iPhone 15 Pro'`.
3. In the app, enter `https://rabotyaga.viralops.ru` and the code. Never paste
   the device secret; the app receives it over HTTPS and saves it to Keychain.
4. Send a harmless chat message, background/foreground the app, then verify that
   the real response and history remain.
5. Exercise a harmless approval-producing operation and verify no work continues
   until one displayed choice is selected.

## Future Shabashka API (design only)

The current demo cards and swipe persistence remain unchanged. A later API can
add these authenticated resources without changing swipe semantics:

- `GET /v1/opportunities` — normalized real jobs with source, URL, budget,
  required skills and Hermes rationale;
- `POST /v1/opportunities/{id}/decisions` — `passed`, `saved` or `interested`;
- `POST /v1/opportunities/{id}/draft` — ask Hermes to prepare a response draft;
- `POST /v1/opportunities/{id}/submit` — always creates a concrete pending
  approval; it never sends from a swipe or from silence.

Source filters must include Telegram bots, Mini Apps, sites, AI agents, Python,
automation and API integrations, while excluding YouTube production, video
editing and HOOK agency services.
