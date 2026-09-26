# MultiPlay architecture

## Design rule

MultiPlay shares infrastructure, not provider semantics.

A generic protocol family may understand JSON-RPC envelopes, HTTP action fields or
WebSocket framing. It must not decide that a field means a spin, purchase, free spin,
picker or terminal state for a specific provider. That interpretation belongs to the
provider adapter.

## Layers

### 1. Evidence acquisition

Inputs may include:

- HAR request/response traffic;
- browser-captured traffic;
- WebSocket frames;
- loaded scripts/bootstrap data;
- screenshots/DOM observations used as semantic evidence.

Playwright is optional and lives outside the core. Browser automation acquires evidence;
it does not own provider logic.

### 2. Protocol-family detection

Several families may coexist in one game.

Examples:

- HTTP bootstrap + WebSocket runtime;
- HTTP bootstrap + JSON-RPC gameplay;
- multiple HTTP action endpoints.

The analyzer therefore builds zero or more ProtocolContract objects instead of forcing a
single winner.

### 3. Provider adapter

Each provider owns:

- recognition/classification;
- action semantics;
- provider state machine;
- purchase/feature semantics;
- provider-specific request building;
- provider-specific response validation;
- terminal-state rules;
- any concurrency/runtime restrictions.

Provider adapters must not import another provider adapter.

### 4. Generic feature vocabulary

Cross-provider reporting may normalize only the structural concepts:

- FEATURE_SESSION
- FEATURE_ROUND
- FEATURE_CHOICE

The original provider wire is always preserved.

### 5. Completeness gate

A successful HTTP response is not sufficient for completion.

Unknown executable branches, unresolved choices, unstable request shapes, unknown terminal
conditions or missing continuations keep the result PARTIAL_REQUIRES_REVIEW.

### 6. Provider knowledge

Every analysis run can update:

knowledge/providers/<provider>/endpoints.json
knowledge/providers/<provider>/runs/<run>.json

When a provider analysis is explicitly closed, status.json is written.

Endpoint knowledge is environment-aware:

- demo_state
- live_state

A provider can therefore be fully documented in demo while still remaining unverified in
live.

## Endpoint record

An endpoint record includes:

- provider;
- protocol family;
- action;
- HTTP/WebSocket transport;
- method;
- endpoint template;
- request format;
- response format;
- dynamic fields;
- sensitive fields;
- evidence references;
- demo validation state;
- live validation state.

Tokens, session IDs, cookies, CSRF values and credentials are represented only by
placeholders.

## Hard constraints

- No game-title hardcoding as a normal strategy.
- No cross-provider semantic reuse.
- New HAR/runtime evidence overrides historical assumptions.
- Unknown wire stays unknown.
- Persist RAW evidence when available.
- A live environment must never reuse a demo token/session.
