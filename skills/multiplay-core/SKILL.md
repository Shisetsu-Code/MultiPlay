---
name: multiplay-core
description: Core context and invariants for Shisetsu-Code/MultiPlay multi-provider protocol analysis.
---

# MultiPlay core

Read these before changing architecture or provider behavior:

- docs/ARCHITECTURE.md
- docs/MIGRATION.md
- knowledge/legacy/LEARNINGS.md
- knowledge/providers/<active-provider>/status.json when present
- knowledge/providers/<active-provider>/endpoints.json when present

## Invariants

1. Share infrastructure, never provider semantics.
2. Protocol-family modules understand structure only.
3. Provider-specific meaning belongs under providers/<provider>.
4. A capture may contain several protocol families simultaneously.
5. Do not hardcode behavior by game title/slug as a normal strategy.
6. Unknown executable wire/state/choice => PARTIAL_REQUIRES_REVIEW.
7. New current evidence overrides historical observations.
8. Preserve evidence and exact wire shape before normalization.
9. Do not persist tokens, cookies, CSRF, sessions, credentials or secrets.
10. FEATURE_SESSION / FEATURE_ROUND / FEATURE_CHOICE are reporting abstractions only;
    preserve the original provider wire.

## Endpoint knowledge

Every completed provider analysis must have an endpoint ledger.

Do not mark a provider analysis complete if required executable branches remain unresolved.

Demo validation and live validation are independent.
