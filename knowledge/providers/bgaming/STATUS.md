# BGaming migration status

Updated: 2026-09-26

## Repository

Shisetsu-Code/MultiPlay

## Current implementation state

Implemented and covered by CI:

- provider package isolation under src/multiplay/providers/bgaming/
- runtime classification:
  - api-v2
  - legacy-lines
  - hyperhive-jsonrpc
  - switchable-container
- provider semantic validation gates
- provider-specific endpoint ledger enrichment
- switch_variant GET endpoint capture
- session/token-safe endpoint sanitization
- bootstrap window.__OPTIONS__ parser
- client-side advertised action contract discovery
- dynamic contiguous index-domain proof
- API-v2 feature/continuation state model
- HyperHive observed-wire templates
- API-v2 observed-wire templates
- BGaming catalog HTML parser
- ephemeral demo token protection
- CLI command:
  - multiplay bgaming-catalog

## Historical knowledge preserved

See MIGRATION.md.

Important retained findings include:

- HyperHive error 51100 can result from changing the demonstrated wire shape.
- state_lock field presence matters.
- req.bet scalar type can matter.
- custom_req selectors must not be normalized away.
- API-v2 server flow.available_actions is dispatch authority.
- dynamic picker domains require a proven rejection boundary.
- switchable child identifiers must not be hardcoded.

## Not yet revalidated in MultiPlay

No current real BGaming HAR corpus has been ingested into this clean repository yet.

Therefore:

- knowledge/providers/bgaming/endpoints.json has not been finalized from current evidence;
- the historical ~215-game corpus has not been rerun;
- no provider-wide completion claim is valid yet;
- live_state must remain UNKNOWN until explicit live validation.

## Evidence needed to close BGaming

Prefer fresh captures from the current public/demo runtime.

Representative successful evidence is needed for each family encountered:

### api-v2

- init/bootstrap
- base spin
- all advertised purchases/boosters
- continuations
- finite choices when advertised
- terminal return to base

### hyperhive-jsonrpc

- init
- successful base play
- exact state_lock behavior
- exact bet scalar/type
- custom_req when present
- purchased_feature variants when advertised
- continuation actions

### legacy-lines

- init with line_bets/lines
- full per-line spin request
- demonstrated non-wagering terminal/finish path when required

### switchable-container

- lobby/container bootstrap
- variant switch GET
- fresh child identifier/api/CSRF response
- child init/spin

### dynamic pickers

Only when encountered:

- current client serializer evidence
- fresh-session index probes
- repeated rejection at the first invalid boundary

## Next operational step

Generate the current target corpus:

    multiplay bgaming-catalog --output bgaming-catalog.json

Then capture/analyze representative games per detected runtime family.

Do not repeat every historical experiment blindly. Start by classifying current games,
then sample each distinct family/shape and expand only where evidence reveals a new branch.
