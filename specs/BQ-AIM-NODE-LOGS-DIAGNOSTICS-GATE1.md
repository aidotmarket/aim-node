# BQ-AIM-NODE-LOGS-DIAGNOSTICS — Gate 1 Design Review

## Summary

Replace `LogsPlaceholder` with a real-time log viewer with level filtering, search, and WebSocket live streaming. This is a **frontend-only** BQ — the backend is fully implemented with both REST and WebSocket endpoints.

## Current State

### Backend (complete — `aim_node/management/logs.py`)
- `RingBufferHandler`: captures logs into bounded deque (1000 entries), supports subscribers via `asyncio.Queue`
- `GET /api/mgmt/logs`: tail endpoint with query params `level` (DEBUG/INFO/WARNING/ERROR/CRITICAL), `limit` (1-1000, default 100), `since` (ISO8601 timestamp)
- `WS /api/mgmt/logs/stream`: real-time WebSocket stream. Origin must be localhost/127.0.0.1. Remote access requires `session_token` query param. Sends `LogEntry` JSON per message.
- `LogEntry` shape: `{ timestamp: str, level: str, logger: str, message: str, extra: dict|null }`

### Frontend
- Empty placeholder at `/logs` in AppLayout

## Design

### Layout

Single page at `/logs`. Two zones:

1. **Controls Bar** — top fixed: level filter, search, live/paused toggle, clear button
2. **Log Table** — scrollable virtualized list of log entries

### Zone 1: Controls Bar

Horizontal bar with:
- **Level filter**: dropdown or segmented control — All / DEBUG / INFO / WARNING / ERROR / CRITICAL
- **Search**: text input filtering on `message` field (client-side filter on loaded entries)
- **Live toggle**: button switching between "Live" (WebSocket streaming) and "Paused" (static snapshot)
- **Clear**: clears the local display buffer (does not affect server-side ring buffer)

### Zone 2: Log Table

| Column | Width | Content |
|--------|-------|---------|
| Timestamp | 180px | Formatted local time (HH:mm:ss.mmm or full datetime) |
| Level | 80px | Color-coded badge: DEBUG=gray, INFO=blue, WARNING=amber, ERROR=red, CRITICAL=red-bold |
| Logger | 150px | Logger name (truncated with tooltip) |
| Message | flex | Full message text, wrapping |

**Behavior**:
- Initial load: `GET /api/mgmt/logs?limit=200` to populate
- Live mode: connect to `WS /api/mgmt/logs/stream`, append entries to display buffer
- Display buffer capped at 2000 entries client-side (oldest dropped)
- Auto-scroll to bottom when in live mode and user hasn't scrolled up
- Scroll lock: if user scrolls up, pause auto-scroll; "Jump to bottom" button appears
- Click on a row expands to show `extra` fields as formatted JSON

### WebSocket Connection

- Connect on page mount if live mode (default)
- Reconnect with exponential backoff on disconnect (1s, 2s, 4s, max 30s)
- Connection status indicator next to Live toggle: green dot = connected, yellow = reconnecting, red = failed
- Pass `session_token` from Zustand node store if available (for remote-bind scenarios)

### Edge States

| Condition | Behavior |
|-----------|----------|
| Empty log buffer | "No log entries yet. Logs will appear as the node operates." |
| WebSocket connection failed | Fall back to REST polling (`GET /api/mgmt/logs?since={last_timestamp}`) every 5s. Show connection status as red. |
| WebSocket origin rejected (remote access) | Show "WebSocket streaming unavailable for remote connections. Using REST polling." Auto-switch to poll mode. |
| Level filter active + live mode | Filter applied client-side to incoming WebSocket entries |
| Node in setup_incomplete/locked | Router redirects before reaching logs page |

### Refresh Strategy (Paused Mode)

- `GET /api/mgmt/logs?level={level}&limit=200`: `staleTime: 10_000`, `refetchInterval: 30_000`
- User can manually refresh via a refresh button

### Support Bundle (Deferred)

A "Download Support Bundle" feature (collecting logs + config + metrics into a zip) would be valuable but requires backend work to aggregate data. Deferred to v2 or a follow-up BQ.

## Dependencies

- `aim_node/management/logs.py` — RingBufferHandler, logs_tail, logs_stream_ws (all exist, read-only)
- Frontend: React Query (installed), Zustand (for connection state)
- **No new dependencies required** — WebSocket is native browser API

## Estimated Effort

| Area | Hours |
|------|-------|
| Frontend: Controls bar (filter, search, toggle) | 2 |
| Frontend: Log table with expand/collapse | 3 |
| Frontend: WebSocket connection + reconnect + fallback | 2.5 |
| Frontend: Auto-scroll + scroll lock | 1 |
| Tests: component tests | 1.5 |
| **Total** | **10** |

## Success Criteria

1. Logs page loads with initial REST fetch of recent entries
2. Live mode streams via WebSocket with < 500ms latency
3. Level filter works in both live and paused modes
4. Search filters entries client-side in real-time
5. Click-to-expand shows extra fields
6. Auto-scroll with scroll lock works correctly
7. WebSocket reconnect with backoff functions
8. Fallback to REST polling when WebSocket unavailable
9. Existing tests remain green, new component tests added
