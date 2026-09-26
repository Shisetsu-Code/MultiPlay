---
name: live-validation
description: Revalidate an already documented MultiPlay provider endpoint against an explicitly authorized live environment.
---

# Live validation

Read:

- docs/LIVE_VALIDATION.md
- knowledge/providers/<provider>/endpoints.json
- knowledge/providers/<provider>/status.json

Only validate endpoints that already have a documented demo/observed contract.

## Rules

- Establish a fresh live session.
- Never reuse demo tokens or session state.
- Never store credentials, cookies, tokens, CSRF values or wallet/account secrets.
- Compare the live wire to the stored contract before interpreting the result.
- Substitute only fields already classified as dynamic.
- Do not silently mutate the contract to make a mismatching live endpoint pass.
- A mismatch becomes evidence and REQUIRES_REVIEW.
- Mark live_state VERIFIED only after request shape, response shape and provider-specific
  state/accounting checks all pass.
