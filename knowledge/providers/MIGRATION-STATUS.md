# Provider migration status

Updated: 2026-09-29

MultiPlay now has isolated provider analyzers registered for all eight provider
families currently in scope.

| Provider | Adapter key | Migrated evidence contract | Current live/demo revalidation |
| --- | --- | --- | --- |
| BGaming | `bgaming` | API-v2, legacy-lines, HyperHive JSON-RPC, switchable | broad current recovery corpus |
| Yggdrasil | `yggdrasil` | form-encoded `fn=play`, observed `BB_*` purchases | partial: base spin still needed |
| Pragmatic Play | `pragmatic` | gameService actions, `na` continuations | historical contract migrated; fresh corpus pending |
| 1Spin4Win / D1 | `one_spin4win` | A/u2 WebSocket type 0/1/3 and feature `st` states | historical contract migrated; fresh corpus pending |
| Belatra | `belatra` | `/game` enter/start/finish phase contract | historical contract migrated; fresh corpus pending |
| RubyPlay | `rubyplay` | gameserver actions, action counter, next_action, indexed choices | historical contract migrated; fresh corpus pending |
| Red Tiger | `redtiger` | platform/game settings, spin, featureBuy, choice | historical contract migrated; fresh corpus pending |
| 3 Oaks | `3oaks` | `/api/v1/games/<slug>/play` command transport | historical contract migrated; fresh corpus pending |

## Meaning of migrated

A migrated provider has:

- an isolated `ProviderAdapter`;
- provider recognition based on wire/host evidence;
- conservative provider-level validation;
- provider-specific endpoint-ledger generation;
- no dependency on Tester-Spin at runtime;
- no title/slug hardcoding;
- fail-closed behavior for unknown or incomplete branches.

Migration does **not** mean every historical game has been revalidated against the
current provider runtime. Historical observations are used as regression contracts;
fresh evidence remains authoritative.

## Additional core migration

HAR ingestion now imports Chromium-style WebSocket messages from
`_webSocketMessages`, `webSocketMessages`, or `_webSocketFrames`. This allows
1Spin4Win/D1 captures to enter the same provider-neutral pipeline as HTTP providers.

The generic HTTP detector also recognizes structurally action-routed endpoint leaves
such as `/spin`, `/choice`, `/settings`, and `/game` when the action is not
encoded in the request body. Provider semantics remain in their adapters.
