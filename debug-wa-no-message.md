# Debug Session: WhatsApp messages not flowing

- sessionId: `wa-no-message`
- projectRoot: `e:\project\website-bengkel-dashboard`
- debugEvidenceDir: `C:\Users\NotSec\AppData\Local\Temp\trae-debug\website-bengkel-dashboard-wa-no-message`
- logPath: `C:\Users\NotSec\AppData\Local\Temp\trae-debug\website-bengkel-dashboard-wa-no-message\trae-debug-log-wa-no-message.ndjson`
- envPath: `C:\Users\NotSec\AppData\Local\Temp\trae-debug\website-bengkel-dashboard-wa-no-message\wa-no-message.env`

## Hypotheses

1. The old bridge process still owns port 9090, so Knightbot-MD is not the active provider.
2. Knightbot receives messages but `forwardIncoming` filters them or cannot reach the FastAPI webhook.
3. FastAPI rejects inbound messages because the internal token differs between Knightbot and the API.
4. The API can receive inbound messages, but outbound sends fail because its bridge status is not connected.

## Evidence collected

- User reports `EADDRINUSE` on `127.0.0.1:9090` and no response to `.ping` or website messages.
- Existing status probe returned `status: connected`, `provider: baileys`, `authedNumber: 6287866821436`.
- Knightbot source identifies its provider as `knightbot-md`; therefore the reported active provider is not Knightbot-MD.

## Progress

- progress_status: collecting-runtime-evidence
- conclusion: hypotheses not yet fully classified
