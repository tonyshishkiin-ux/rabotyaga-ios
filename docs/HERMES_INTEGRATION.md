# Hermes integration for Работяга iOS 1.2

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
  HTTPS + Tailscale identity + per-device HMAC
      ↓
Tailscale Serve (tailnet only, no Funnel)
      ↓
127.0.0.1:8787 Rabotyaga Gateway
  DPAPI device keys, replay/idempotency ledger, local chat projection
      ↓
Hermes protected named pipe → one-use ticket → loopback WebSocket
      ↓
Existing Hermes session, local Qwen and configured tools
```

Tailscale is the encrypted network boundary; the per-device key is an additional
application boundary. A tailnet member without a valid device key cannot submit
messages. Revocation sets the device inactive immediately, independently of
Tailscale membership.

## API v1

`POST /v1/pair` is the only unauthenticated mutation. It accepts a one-use code
over HTTPS and returns one device credential. All other routes require the four
`X-Rabotyaga-*` HMAC headers.

- `GET /v1/chat` — durable message projection, task status, pending approvals;
- `POST /v1/chat/messages` — idempotent submission with client `request_id`;
- `POST /v1/chat/approvals/{prompt_id}` — one explicit choice for one projected
  prompt and execution generation;
- `DELETE /v1/device` — revoke the current device;
- `GET /v1/health` — minimal liveness, no Hermes or identity metadata.

No endpoint can enable YOLO mode, set global approval policy, expose credentials,
or execute an arbitrary RPC method. Missing user input never becomes approval.

## Reconnect and long tasks

Hermes owns the canonical transcript and task lifetime. The bridge keeps its own
projection so HTTP polling is simple and reliable on iOS 15. On reconnect it
resumes only the device's mapped Hermes session, hydrates the durable transcript,
pending admissions and pending prompts, then continues consuming events. Client
retries reuse the original `request_id`; Hermes' admission ledger and the bridge
database both reject duplicate work.

The iOS app caches rendered messages under iOS Data Protection and restores them
immediately after relaunch. Key material remains in Keychain. While a turn is
running the app polls the small state endpoint; backgrounding does not cancel the
Hermes turn, and foregrounding reconciles from the server.

## Tailscale deployment (requires operator approval)

The safe publication command is deliberately not run automatically:

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:8787
tailscale serve status
```

Do not use `tailscale funnel`, router port forwarding, `0.0.0.0`, or a public DNS
record. Before applying the command, confirm that the iPhone is online in the same
tailnet. To remove publication, use the current Tailscale CLI's documented Serve
reset command and verify `tailscale serve status` is empty.

## Device enrollment

1. Start the bridge in a foreground PowerShell window.
2. After Tailscale Serve is explicitly enabled, create a one-time pairing code:
   `.\scripts\hermes_gateway.ps1 -Action pair -DeviceName 'iPhone 15 Pro'`.
3. In the app, enter only the `https://…ts.net` Serve URL and the code. Never paste
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
