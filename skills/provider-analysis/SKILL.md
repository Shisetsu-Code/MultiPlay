---
name: provider-analysis
description: Analyze one MultiPlay provider from evidence through exhaustive path coverage and endpoint documentation.
---

# Provider analysis

Use together with multiplay-core.

## Start

1. Identify exactly one active provider.
2. Read its legacy observations only as hypotheses.
3. Read current endpoint/status knowledge if present.
4. Freeze the target corpus/source for the run.

## Evidence order

Prefer:

1. bootstrap/network protocol;
2. request/response HAR;
3. scripts/configuration;
4. real browser action -> network correlation;
5. screenshot/DOM interpretation.

Visual evidence may explain semantics but must not invent wire formats.

## Protocol

Detect all structural families present. Do not force a provider into one family.

## Provider semantics

Implement semantics only in the active provider adapter.

Do not import or copy semantic rules from another provider.

## Coverage

Cover:

- base action;
- every advertised wager/ante/booster/purchase mode;
- continuations;
- free-spin/bonus entry and exit;
- collect/finalization;
- every demonstrated selectable branch;
- nested choices.

Use fresh rounds/sessions for sibling branches when the protocol consumes state.

Unknown branch or terminal rule stays partial.

## Completion

Before declaring the provider finished:

1. all required executable branches are covered or explicitly unresolved;
2. endpoint formats are written to knowledge/providers/<provider>/endpoints.json;
3. sensitive values are redacted;
4. provider status is finalized with unresolved reasons, if any.

Use:

    multiplay analyze-har <capture.har> --provider <provider> --source-ref <evidence>
    multiplay finalize-provider <provider>

Never silently promote demo observations to live validation.
