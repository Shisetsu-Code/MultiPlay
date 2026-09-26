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
- non-wagering catalog sweep with per-game failure retention and runtime-family summary
- CLI commands:
  - multiplay bgaming-catalog
  - multiplay bgaming-probe
  - multiplay bgaming-sweep
  - multiplay capture-har
  - multiplay analyze-dir
- recursive batch HAR ingestion with consolidated endpoint knowledge
- batch summaries grouped by runtime family and repeated semantic blockers
- headed manual browser evidence capture without provider-control hardcoding
- Playwright causal explorer: screenshot/DOM/canvas candidates -> real click -> HTTP/WS delta
- discovered click coordinates are run evidence only and never provider contracts

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

## Current live-catalog revalidation

A non-wagering sweep of the current public catalog completed successfully in GitHub Actions
on 2026-09-26.

Observed catalog:

- 233 Slots records
- catalog crawl authoritative
- 233 probe attempts
- 107 successful bootstrap/init analyses
- 126 unresolved probe failures

Runtime-family observations from successful probes:

- api-v2: 72
- hyperhive-jsonrpc: 32
- legacy-lines: 3
- switchable-container: 1

The dominant unresolved transport condition was provider HTTP 429 rate limiting:

- HTTP 429: 110
- unresolved demo resolution: 15
- stale demo HTTP 404: 1

These failures are not evidence that the games use an unsupported protocol.

Current endpoint evidence includes API-v2/legacy init endpoints with sanitized shape:

    POST https://demo.bgaming-network.com/api/<Identifier>/<id>/<session>

The sweep still does not demonstrate base spin/purchase wire for those games, so no
provider-wide completion claim is valid and live_state remains UNKNOWN.

See SWEEP-2026-09-26.md.

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

Then run the non-wagering bootstrap/init sweep against the current catalog:

    multiplay bgaming-sweep --catalog bgaming-catalog.json --output captures/bgaming/sweep.json

Use `bgaming-probe` for individual follow-up targets.

For runtime action evidence, prefer the Playwright causal explorer:

    multiplay bgaming-browser-discover \
      --catalog bgaming-catalog.json \
      --family hyperhive-jsonrpc \
      --output-dir captures/bgaming/hyperhive-browser

It chooses a representative by current runtime evidence, captures screenshots, discovers
visible controls, performs real Playwright clicks and records the HTTP/WebSocket effects.
No game title, button text, endpoint, payload or coordinate is hardcoded.

Use interactive HAR capture only if the causal explorer cannot expose a required branch.

Then capture/analyze representative games per detected runtime family.

Suggested local flow:

    multiplay capture-har <demo-url> --output captures/bgaming/<game>.har
    multiplay analyze-dir captures/bgaming --provider bgaming --output captures/bgaming/report.json

Do not repeat every historical experiment blindly. Start by classifying current games,
then sample each distinct family/shape and expand only where evidence reveals a new branch.
