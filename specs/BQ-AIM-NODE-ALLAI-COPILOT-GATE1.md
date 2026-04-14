# BQ-AIM-NODE-ALLAI-COPILOT — Gate 1 Design Review (R2)

## Summary

Upgrade the existing AllAIChat floating widget from basic text-only chat to a full copilot with conversation persistence, action confirmations, suggested prompts, markdown rendering, and 2 new local tools. Four additional tools (`draft_publish_payload`, `estimate_pricing`, `recommend_spend_cap`, `compare_provider_versions`) are **deferred** until their source data contracts are finalized by other BQs.

## Current State

### Backend (`aim_node/management/allai.py`)
- Agentic chat: `POST /allai/chat` with auto-execution loop (max 5 depth)
- Confirmation: `POST /allai/confirm` — in-memory action cache (process-global dict, no TTL, no persistence)
- Context gathering: node status, sessions, dashboard, discovered tools, marketplace state
- 6 implemented tools: `inspect_local_config`, `test_market_auth`, `scan_provider_endpoint`, `list_local_tools`, `tail_recent_logs`, `explain_last_failure`
- Response: `{ reply, conversation_id, proposed_actions[], suggestions[] }`

### Frontend (`frontend/src/components/AllAIChat.tsx`)
- Floating FAB + 360×480 chat panel, mounted in AppLayout and SetupLayout
- Basic send/receive with retry on error
- **Missing**: conversation_id tracking, proposed_actions rendering, confirmation buttons, suggestions, markdown rendering, loading states, Zustand persistence

## Design

### Frontend Upgrades

#### 1. Conversation ID Persistence
- Track `conversation_id` in Zustand store (survives panel close/reopen within same page session, lost on full page refresh)
- Pass to every `/allai/chat` request
- "New conversation" button in header resets conversation_id and clears messages

#### 2. Proposed Actions UI
When `proposed_actions` is non-empty:
- Render each action as a compact card below the reply: tool name badge, description text
- Two buttons: "Approve" → `POST /allai/confirm { action_id, approved: true }`, "Dismiss" → `{ approved: false }`
- Per-action loading spinner while confirmation in-flight
- After confirmation, append result as assistant message or inline result block
- **Stale action handling**: if confirm returns 404 (action_id expired/unknown), show inline error "This action has expired. Please ask again." Remove the action card.
- **Duplicate click prevention**: disable both buttons immediately on first click

#### 3. Suggestions
When `suggestions` is non-empty:
- Render as clickable pill buttons below the reply
- Click fills input and auto-sends
- Suggestions disappear after one is clicked or after next user message

#### 4. Markdown Rendering
- Render assistant replies with: bold, italic, code blocks, inline code, links, unordered/ordered lists
- **New dependency required**: `react-markdown` or `marked` + `DOMPurify` (NOT installed — must add at Gate 2)
- Sanitize all HTML output

#### 5. Loading States
- Typing indicator (animated dots) while waiting for backend response
- **Backend enhancement**: Add `tool_executions: list[{tool_name, status}]` field to `AllAIChatResponse` so frontend can show "Running inspect_local_config..." without brittle reply-text sniffing. The existing `_append_execution_reply` stays for the text content; this new field provides structured metadata.

#### 6. Chat State in Zustand
- Store: `{ messages[], conversationId, isOpen }` in a Zustand slice
- Survives panel close/reopen (same page session)
- Lost on full page refresh (no localStorage — not supported)
- Process restart on backend clears pending action cache — frontend handles 404 gracefully (see stale action handling above)

#### 7. Panel Close/Reopen Behavior
- Closing panel preserves all state (messages, conversationId, pending actions)
- Reopening restores chat exactly as left
- Pending action cards remain visible after reopen — if backend was restarted, confirm will 404 and show expiry message

#### 8. Keyboard & Accessibility
- Enter to send, Shift+Enter for newline
- Escape to close panel
- Scroll to bottom on new message
- Auto-focus input on open
- ARIA labels on action buttons

### Backend — 2 New Local Tools

#### `generate_input_output_schema`
- **Purpose**: Generate a JSON Schema template for a tool's input/output
- **Data source**: Discovered tool cache (`read_store(data_dir, "discovered_tools")`) — tools already have `input_schema` and `output_schema` from upstream `/tools/list`
- **Params**: `{ tool_name: str }` (or `tool_id`)
- **Logic**: Look up tool in discovered cache by name/id. Return existing schemas if present. If schemas are empty `{}`, return a template with common fields (`type: "object"`, `properties: {}`, `required: []`) and a note that the user should fill in their tool's specific fields.
- **Error**: `{"error": "tool_not_found"}` if tool doesn't exist in cache

#### `test_tool_invocation`
- **Purpose**: Send a test call to a discovered tool via the upstream MCP endpoint
- **Data source**: Upstream URL from config → `POST {upstream_url}/tools/call` with `{ name, arguments }` — this is the actual MCP-style tool invocation contract used by `aim_node/management/tools.py`
- **Params**: `{ tool_name: str, arguments?: dict }` — arguments default to `{}`
- **Logic**: Look up tool in discovered cache to verify it exists. Build URL via `_tools_call_url(upstream_url)`. POST with `{ "name": tool_name, "arguments": arguments }`. Timeout 10s.
- **Returns**: `{ "success": bool, "status_code": int, "response": any, "latency_ms": float }` on success, `{ "success": false, "error": str }` on failure
- **Error**: `{"error": "tool_not_found"}` if not in cache, `{"error": "upstream_not_configured"}` if no upstream URL

Both tools follow existing pattern: async handler in `_LOCAL_TOOL_HANDLERS`, added to `DEFAULT_ALLOWED_TOOLS`.

### Deferred Tools (Not In This BQ)

| Tool | Reason Deferred |
|------|----------------|
| `draft_publish_payload` | Publish payload schema requires listing_id, taxonomy tags, sample IO, pricing formula — discovered tool cache doesn't contain enough. Depends on Seller Publish contracts. |
| `estimate_pricing` | Needs avg latency (not in metrics summary) and comparable listings endpoint (doesn't exist locally). |
| `recommend_spend_cap` | Buyer-mode concern — no spend-cap config API or local persistence target exists yet (BQ-AIM-NODE-BUYER-MODE). |
| `compare_provider_versions` | Marketplace tool responses don't reliably carry version fields. |

These will be added as follow-up BQs once their upstream contracts stabilize.

### Backend Enhancement: Structured Tool Execution Metadata

Add to `AllAIChatResponse`:
```python
class ToolExecution(BaseModel):
    tool_name: str
    status: str  # "executed" | "error"
    action_id: str

class AllAIChatResponse(BaseModel):
    reply: str
    conversation_id: str
    proposed_actions: list[ProposedAction] | None = None
    suggestions: list[str] | None = None
    tool_executions: list[ToolExecution] | None = None  # NEW
```

Populated from the `executed` list in `allai_chat()` — already tracked, just not returned.

## Edge States

| Condition | Behavior |
|-----------|----------|
| Facade unavailable (412) | Chat shows "Complete setup to use allAI." Input disabled. |
| Backend unreachable | Error card with retry (existing behavior). |
| Stale action_id (404 on confirm) | Show "This action has expired." Remove action card. |
| Duplicate approval click | Buttons disabled on first click. |
| Panel close/reopen | State preserved in Zustand. |
| Process restart | Backend action cache cleared. Frontend pending actions get 404 on confirm — handled gracefully. |
| Multi-tab | Each tab has independent Zustand state. No cross-tab sync in v1. |
| No discovered tools | `generate_input_output_schema` and `test_tool_invocation` return `{"error": "tool_not_found"}`. allAI reply explains the issue. |

## Dependencies

- `aim_node/management/allai.py` — add 2 new tools, add `tool_executions` to response
- `aim_node/management/tools.py` — `_tools_call_url()`, discovered tool cache, `DiscoveredTool` dataclass
- `aim_node/management/metrics.py` — read-only (context gathering, no new usage)
- `aim_node/management/marketplace.py` — read-only (context gathering, no new usage)
- `frontend/src/components/AllAIChat.tsx` — major rewrite
- `frontend/src/store/` — new Zustand slice for chat state
- **New dependency**: markdown renderer (NOT installed)

## Estimated Effort

| Area | Hours |
|------|-------|
| Backend: 2 new tool handlers | 2 |
| Backend: ToolExecution response field | 1 |
| Backend: tool + response tests | 2 |
| Frontend: conversation_id + Zustand store | 2 |
| Frontend: proposed actions + confirmations + stale handling | 3 |
| Frontend: suggestions + markdown + loading states | 3 |
| Frontend: keyboard/a11y + panel close/reopen | 1.5 |
| Frontend: component tests | 2.5 |
| **Total** | **17** |

## Success Criteria

1. 8 total tools registered and functional in `_LOCAL_TOOL_HANDLERS`
2. Conversation ID persists across messages and panel close/reopen
3. Proposed actions render with Approve/Dismiss, confirmation works end-to-end
4. Stale action_id (404) handled gracefully with expiry message
5. Suggestions render as clickable pills, auto-send on click
6. Assistant replies render basic markdown
7. Structured `tool_executions` field drives loading indicator (no reply-text sniffing)
8. All edge states handled per table above
9. Existing tests remain green, new tests for 2 tools + ToolExecution + frontend components
