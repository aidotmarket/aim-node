# BQ-AIM-NODE-ALLAI-COPILOT — Gate 1 Design Review

## Summary

Upgrade the existing AllAIChat floating widget from basic text-only chat to a full copilot with conversation persistence, action confirmations, suggested prompts, markdown rendering, and 6 new local tools. The backend already has an agentic chat loop (`/allai/chat`) with auto-execution, confirmation flow, and context gathering — plus 6 implemented tools. This BQ adds the missing frontend features and the remaining 6 backend tools from the Phase 4 plan.

## Current State

### Backend (exists — `aim_node/management/allai.py`)
- Agentic chat endpoint: `POST /allai/chat` with auto-execution loop (max 5 depth)
- Confirmation endpoint: `POST /allai/confirm`
- Context gathering: node status, sessions, dashboard, discovered tools, marketplace state (published tools, earnings summary)
- 6 implemented tools: `inspect_local_config`, `test_market_auth`, `scan_provider_endpoint`, `list_local_tools`, `tail_recent_logs`, `explain_last_failure`
- `AllAIChatResponse` returns: `reply`, `conversation_id`, `proposed_actions[]`, `suggestions[]`

### Frontend (exists — `frontend/src/components/AllAIChat.tsx`)
- Floating FAB + 360×480 chat panel (mounted in both AppLayout and SetupLayout)
- Basic send/receive with retry on error
- **Missing**: conversation_id tracking, proposed_actions rendering, confirmation buttons, suggestions, markdown rendering, persistent history, loading states for tool execution

## Design

### Frontend Upgrades

#### 1. Conversation ID Persistence
- Track `conversation_id` in component state, pass to every `/allai/chat` request
- Reset on explicit "New conversation" button in header

#### 2. Proposed Actions UI
When `proposed_actions` is non-empty in response:
- Render each action as a compact card below the reply:
  - Tool name badge, description text
  - Two buttons: "Approve" (calls `POST /allai/confirm` with `approved: true`) and "Dismiss" (calls with `approved: false`)
- Show spinner on action card while confirmation is in-flight
- After confirmation, append result as a new assistant message (or inline result block)

#### 3. Suggestions
When `suggestions` is non-empty:
- Render as clickable pill buttons below the reply
- Clicking a suggestion fills it as user input and auto-sends

#### 4. Markdown Rendering
- Render assistant replies with basic markdown: bold, italic, code blocks, inline code, links, lists
- Use a lightweight renderer (e.g., `marked` + `DOMPurify`, or `react-markdown` — builder's discretion at Gate 2)
- **Dependency note**: No markdown renderer currently installed. Must add one.

#### 5. Loading States
- Typing indicator (animated dots) while waiting for backend response
- "Running tool..." indicator when backend returns tool execution results in the reply (detected by "Local action results:" in reply text)

#### 6. Chat History Persistence
- Store conversation history in Zustand (in-memory, lost on page refresh)
- Persist `conversation_id` so backend can maintain server-side conversation context across messages
- No localStorage (not supported in this environment)

#### 7. Resize & Accessibility
- Current size (360×480) is fine for v1
- Keyboard navigation: Enter to send, Escape to close
- Scroll to bottom on new message
- Auto-focus input on open

### Backend — 6 New Local Tools

| Tool | Description | Implementation |
|------|-------------|---------------|
| `generate_input_output_schema` | Generate JSON Schema for a tool's input/output based on discovered tool metadata and optional user description | Read discovered tool from store, use existing tool metadata, produce schema template. No LLM call — pattern matching + template. |
| `test_tool_invocation` | Send a test request to a local tool endpoint and return the response | HTTP call to provider adapter's endpoint URL with a test payload. Requires tool_name param. Timeout 10s. |
| `draft_publish_payload` | Generate a draft publish request body for a local tool | Read tool metadata from discovered tools store, format as publish payload matching `/api/mgmt/marketplace/tools/publish` schema. |
| `estimate_pricing` | Suggest pricing for a tool based on latency, compute, and comparable marketplace listings | Read tool metadata + metrics (avg latency). Return suggested price range. Heuristic-based, no LLM. |
| `recommend_spend_cap` | Suggest a daily/monthly spend cap for buyer mode based on usage patterns | Read metrics summary + session history. Return suggested caps. Heuristic-based. |
| `compare_provider_versions` | Compare current tool versions with marketplace-published versions | Read local discovered tools, compare with facade tools list. Return version diff. |

All new tools follow the existing pattern:
- Async function: `_tool_{name}(request, params) -> dict`
- Registered in `_LOCAL_TOOL_HANDLERS` dict
- Added to `DEFAULT_ALLOWED_TOOLS` list
- Each tool operates on local state or facade — no external LLM calls

### Edge States

| Condition | Behavior |
|-----------|----------|
| Facade unavailable (setup incomplete) | Backend returns 412. Frontend shows "Complete setup to use allAI." in chat area. Chat input disabled. |
| Backend unreachable | Existing error handling with retry button (already implemented). |
| No discovered tools | Tools that depend on discovered tools (`generate_input_output_schema`, `test_tool_invocation`, `draft_publish_payload`, `compare_provider_versions`) return informative error: `{"error": "no_tools_discovered", "message": "..."}` |
| Confirmation timeout | Action cards remain until user acts. No auto-timeout in v1. |

## Out of Scope

- Server-side conversation history persistence (backend tracks via conversation_id but no DB storage)
- Streaming responses (future — would require SSE/WebSocket)
- Voice input
- File/image attachments
- Custom tool creation by users
- Resizable chat panel

## Dependencies

- `aim_node/management/allai.py` — extend with 6 new tool handlers
- `aim_node/management/app.py` — routes already mounted (`/allai/chat`, `/allai/confirm`)
- `frontend/src/components/AllAIChat.tsx` — major upgrade
- **New dependency**: markdown renderer (react-markdown, marked, or similar — NOT installed)
- Existing deps: React Query (optional — current implementation uses raw fetch, can stay or migrate), Zustand

## Estimated Effort

| Area | Hours |
|------|-------|
| Backend: 6 new tool handlers + tests | 6 |
| Frontend: conversation_id + actions + confirmations | 4 |
| Frontend: suggestions + markdown + loading states | 3 |
| Frontend: history persistence (Zustand) + keyboard/a11y | 2 |
| Tests: backend tool unit tests (6 tools) | 3 |
| Tests: frontend component tests | 2 |
| **Total** | **20** |

## Success Criteria

1. All 12 tools registered and functional in `_LOCAL_TOOL_HANDLERS`
2. Conversation ID persists across messages within a session
3. Proposed actions render with Approve/Dismiss buttons, confirmation works end-to-end
4. Suggestions render as clickable pills, auto-send on click
5. Assistant replies render basic markdown (bold, code blocks, links, lists)
6. Loading indicator shows during backend processing
7. Edge states handled: facade unavailable, no tools, backend error
8. Existing tests remain green, new tests for all 6 tools + frontend components
9. Chat widget remains functional in both AppLayout and SetupLayout
