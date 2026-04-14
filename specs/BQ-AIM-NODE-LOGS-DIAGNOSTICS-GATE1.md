# BQ-AIM-NODE-LOGS-DIAGNOSTICS — Gate 1 Design Review (R2)

## Summary

Replace `LogsPlaceholder` with a real-time log viewer with level filtering, search, and WebSocket live streaming. Frontend-only BQ — backend fully implemented.

## Current State

### Backend (complete — `aim_node/management/logs.py`)
- `RingBufferHandler`: bounded deque (1000 entries), subscriber queues
- `GET /api/mgmt/logs?level=&limit=&since=`: REST tail (default 100, max 1000)
- `WS /api/mgmt/logs/stream`: real-time WebSocket stream
  - **Origin check order**: first rejects any non-loopback origin (must be `http://localhost` or `http://127.0.0.1`), then checks `session_token` if `remote_bind` is enabled. In practice, remote browser origins are blocked before token auth is reached.
- `LogEntry` shape: `{ timestamp, level, logger, message, extra }`

### Frontend
- Empty placeholder at `/logs`

## Design

### Controls Bar

- **Level filter**: segmented control — All / DEBUG / INFO / WARNING / ERROR / CRITICAL
- **Search**: text input, client-side filter on `message` field
- **Live/Paused toggle**: switches between WebSocket streaming and static snapshot
- **Clear**: clears local display buffer only

### Log Table

Standard scrollable list (no virtualization needed — buffer capped at 2000 client-side entries).

| Column | Width | Content |
|--------|-------|---------|
| Timestamp | 180px | HH:mm:ss.mmm |
| Level | 80px | Color badge: DEBUG=gray, INFO=blue, WARNING=amber, ERROR/CRITICAL=red |
| Logger | 150px | Truncated, tooltip on hover |
| Message | flex | Full text, wrapping |

Click row → expand to show `extra` fields as formatted JSON.

### WebSocket Connection

- Connect on mount if live mode (default on)
- **Loopback only**: WebSocket streaming works only when the UI is accessed from localhost/127.0.0.1 (backend enforces origin check). No session_token handling needed in v1 — the token check is only reachable in remote_bind mode, which is behind the origin gate.
- Reconnect with exponential backoff (1s, 2s, 4s, max 30s)
- Connection status indicator: green = connected, yellow = reconnecting, red = failed/unavailable

### Fallback: REST Polling

When WebSocket is unavailable (connection refused, remote access, or user preference):
- Poll `GET /api/mgmt/logs?since={last_timestamp}&level={level}&limit=50` every 5s
- Append new entries to display buffer
- Show "Using REST polling" indicator

### Edge States

| Condition | Behavior |
|-----------|----------|
| Empty buffer | "No log entries yet." |
| WebSocket refused | Auto-fallback to REST polling. Status indicator red. |
| Remote access (non-loopback origin) | WebSocket will fail. Show "Live streaming unavailable for remote connections." Auto-switch to REST polling. |
| Level filter + live mode | Filter applied client-side to incoming entries |
| Buffer overflow (>2000) | Drop oldest entries |

### Refresh Strategy (Paused Mode)

- `GET /api/mgmt/logs?level={level}&limit=200`: `staleTime: 10_000`, manual refresh button

## Dependencies

- Backend: all routes exist, read-only
- Frontend: React Query (installed), native WebSocket API
- **No new dependencies required**

## Estimated Effort

| Area | Hours |
|------|-------|
| Frontend: Controls bar | 1.5 |
| Frontend: Log table with expand | 2.5 |
| Frontend: WebSocket + reconnect + fallback | 2.5 |
| Frontend: Auto-scroll + scroll lock | 1 |
| Tests: component tests | 1.5 |
| **Total** | **9** |

## Success Criteria

1. Logs page loads with REST fetch of recent entries
2. Live mode streams via WebSocket (loopback only)
3. Level filter and search work in both modes
4. Click-to-expand shows extra fields
5. Auto-scroll with scroll lock
6. Graceful fallback to REST polling when WebSocket unavailable
7. Existing tests green, new tests added
