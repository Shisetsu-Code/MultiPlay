# Migration from previous work

MultiPlay is a clean implementation, not a blind copy of the old repositories.

## Sources

### Tester-Spin

The main historical implementation source.

Relevant checkpoints include:

- 9ddbbd2b4a8eab587b0846e8ab7bc4d2f3acd99f — minimal 3 Oaks catalogue crawler.
- 5ca4699ff1e3bb0709cb45509028a821c9137b56 — isolated standalone providers baseline.
- b1e1d6fed749ce5cb6db72cefb93dcdad2035c1a — BGaming/HyperHive wire-fidelity work.
- 8848f1e — exhaustive-path work across providers.

The old code remains valuable as a source of demonstrated provider contracts and regression
fixtures. It is not imported as a runtime dependency.

### Tester-definitivo

Useful clean-room concepts retained:

- protocol-first HAR analysis;
- conservative transition inference;
- PARTIAL/REQUIRES_REVIEW when evidence is incomplete;
- provider-neutral core;
- no requirement that Playwright be part of the protocol core.

### Play-Ci

The remote repository currently only contains its initialization commit. The later browser
analysis work therefore cannot be treated as a complete remote source tree.

The concepts retained from that work are:

- neutral open/screen/click/network evidence acquisition;
- deviceScaleFactor=1 for coordinate/screenshot correlation;
- iframe/canvas-compatible observation;
- correlate a real user action with the network request it caused;
- use screenshots primarily to interpret semantics when protocol evidence alone is
  ambiguous.

## Migration policy

Historical behavior enters MultiPlay in one of three ways:

1. regression fixture backed by captured evidence;
2. provider documentation marked as a legacy observation;
3. provider adapter code after revalidation against current evidence.

Do not copy old provider behavior into a generic protocol adapter.

## Provider migration order

The architecture is prepared for the providers already analyzed historically:

- Pragmatic Play
- 1Spin4Win / D1
- Belatra
- BGaming
- RubyPlay
- Red Tiger
- 3 Oaks

Each provider is migrated independently and gets its own endpoint ledger.
