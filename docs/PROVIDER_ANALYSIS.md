# Provider analysis workflow

This is the required workflow for finishing one provider.

## Phase A — corpus and evidence

Freeze the provider corpus for the run and retain the catalogue source used.

Capture representative evidence across:

- normal/base play;
- every advertised purchase/ante/booster mode;
- free-spin/bonus entry;
- continuations;
- choices/pickers;
- collect/finish;
- error/rejection cases that reveal the wire contract.

Network evidence is primary. Screenshots/DOM/browser actions are used to establish
causality and semantics, not to invent requests.

## Phase B — protocol families

Detect every structural protocol family present in the evidence.

Do not force HTTP, JSON-RPC and WebSocket into one generic request model.

## Phase C — provider semantics

The provider adapter maps structural transitions to provider semantics.

Any unresolved executable action remains PARTIAL_REQUIRES_REVIEW.

No semantic rule from another provider may be reused merely because field names look
similar.

## Phase D — exhaustive paths

For each executable mode:

1. enter through a fresh valid round/session when required;
2. follow every protocol-required continuation;
3. enumerate every demonstrated selectable branch;
4. use a fresh round/session for sibling branches when the previous choice consumes state;
5. recurse when a choice opens another choice;
6. stop only at a demonstrated terminal condition.

Unknown state or unknown request shape remains partial and is preserved as evidence.

## Phase E — endpoint ledger

Every analyzed transition must be represented in the provider endpoint ledger.

The stored format includes the request template, response shape, dynamic fields and
evidence reference.

No actual token/session/cookie/CSRF value may enter the ledger.

## Phase F — provider finalization

Only run finalize-provider after the analyzed surface has no unresolved required branch.

Example:

    multiplay finalize-provider bgaming

This writes knowledge/providers/bgaming/status.json.

Finalizing demo analysis does not mark any endpoint live-verified.
