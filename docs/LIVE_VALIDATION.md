# Live endpoint validation

The endpoint ledger is designed so demo findings can later be compared with a live
environment without rediscovering the provider from zero.

## Preconditions

- provider analysis has an endpoint ledger;
- the endpoint/action to be tested is already documented;
- live authentication/session material is acquired fresh;
- demo credentials/tokens are never reused;
- live credentials are never written into repository artifacts.

## Validation sequence

For one endpoint fingerprint:

1. load the stored endpoint template;
2. establish a fresh live session;
3. compare live URL/method/transport with the recorded template;
4. compare request keys and required literals;
5. substitute only fields classified as dynamic;
6. perform the explicitly authorized live operation;
7. validate response shape and provider-specific terminal/accounting rules;
8. abort on any wire mismatch instead of adapting silently;
9. mark the endpoint live VERIFIED only after the observed live exchange satisfies the
   stored contract.

The live path is an independent validation layer. A demo-verified endpoint is never
implicitly promoted to live-verified.

## Persistence

Persist:

- endpoint fingerprint;
- redacted request format;
- redacted response shape;
- timestamp;
- validation result;
- evidence reference;
- mismatch notes.

Do not persist:

- session IDs;
- authorization headers;
- cookies;
- CSRF values;
- API keys;
- wallet/account credentials.
