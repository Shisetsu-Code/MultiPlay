# MultiPlay

MultiPlay is the clean multi-provider, multi-protocol successor to the protocol analysis work developed across Tester-Spin, Tester-definitivo and the Play-Ci experiments.

## Goals

- One neutral core for evidence capture, protocol inference, validation and reporting.
- Provider-specific semantics remain isolated under provider adapters.
- Protocol families may share structural parsing (JSON-RPC, HTTP command/state machines, WebSocket frames) but never provider-specific semantics.
- No game-title hardcoding.
- Fail closed: unknown transitions, choices or wire formats remain `PARTIAL_REQUIRES_REVIEW`.
- Preserve RAW evidence and the exact observed request/response shape.
- Record endpoint formats for every provider so demo findings can later be revalidated against a live environment.
- Never persist live/demo session tokens, cookies, CSRF values, credentials or other ephemeral secrets.

## Architecture

```text
evidence acquisition
      |
      v
protocol-family detection
      |
      v
provider adapter
      |
      v
normalized contract
      |
      v
path/feature validation
      |
      +--> provider knowledge / endpoint ledger
      |
      v
demo validation -> optional explicit live validation
```

The generic feature vocabulary is:

- `FEATURE_SESSION`
- `FEATURE_ROUND`
- `FEATURE_CHOICE`

Provider wire formats stay provider-owned.

## Historical sources

The migration preserves knowledge from:

- `Shisetsu-Code/Tester-Spin`
- `Shisetsu-Code/Tester-definitivo`
- the Play-Ci browser/network-analysis work

See `docs/MIGRATION.md` and `knowledge/legacy/LEARNINGS.md`.

## Endpoint ledger

Each provider receives a durable knowledge directory:

```text
knowledge/providers/<provider>/
  endpoints.json
  status.json
  runs/
```

An endpoint record stores the observed URL template, transport, method, action, request/response shape, dynamic fields, evidence and independent demo/live validation state.

Actual token/session/credential values are always redacted.

## Status

Initial architecture/migration baseline. Provider implementations are migrated and revalidated incrementally rather than copied blindly from legacy code.


## BGaming evidence workflow

Install the optional browser capture dependency:

    pip install -e ".[browser]"
    python -m playwright install chromium

Generate the current BGaming catalog:

    multiplay bgaming-catalog --output bgaming-catalog.json

Record one real demo session without hardcoding controls:

    multiplay capture-har "https://demo.bgaming-network.com/play/<Identifier>/FUN" \
      --output captures/bgaming/<game>.har \
      --screenshot captures/bgaming/<game>.png

A headed Chromium window opens. Exercise the base spin and any visible purchase/choice or
continuation paths that need evidence, then press Enter in the terminal. Raw HARs may
contain ephemeral session material; `captures/` is gitignored.

Analyze one capture:

    multiplay analyze-har captures/bgaming/<game>.har --provider bgaming

Or analyze the whole capture directory and consolidate provider knowledge:

    multiplay analyze-dir captures/bgaming --provider bgaming \
      --output captures/bgaming/report.json

The provider endpoint ledger is updated under `knowledge/providers/bgaming/`. Current
evidence always overrides historical migration notes.
