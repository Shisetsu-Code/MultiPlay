# Yggdrasil protocol status

Updated: 2026-09-29

## Current evidence

A browser-causal demo probe on 2026-09-28 demonstrated two distinct purchase
requests for the same Yggdrasil game runtime.

Transport:

```text
POST https://demo.yggdrasilgaming.com/game.web/service?fn=play
Content-Type: application/x-www-form-urlencoded
```

Observed purchase variants:

```text
cmd=BB_5
amount=390
coin=0.1
```

and:

```text
cmd=BB_2
amount=65
coin=0.1
```

The common request shape also contained:

```text
channel
currency
lang
gameid
gameHistorySessionId
gameHistoryTicketId
clientinfo
```

Session/ticket values are ephemeral and must remain redacted.

## MultiPlay implementation

Implemented:

- provider registration under `yggdrasil`;
- provider recognition from Yggdrasil-owned hosts plus `game.web/service?fn=play`;
- form-encoded `cmd` actions preserved as distinct protocol transitions;
- `BB_*` commands classified only as demonstrated purchase commands;
- Google Analytics/other non-Yggdrasil POST traffic excluded from provider endpoint records;
- Yggdrasil session/ticket identifiers redacted during HAR ingestion;
- provider-specific endpoint ledger records for observed `fn=play` commands.

## Current status

`PARTIAL_REQUIRES_REVIEW`.

The two purchase wires are demonstrated, but the current evidence does not prove
the base spin/play command. MultiPlay therefore does not infer the base spin from
`BB_2` or `BB_5` and does not provide a direct Yggdrasil executor yet.

## Evidence still needed

- one ordinary base spin request;
- response semantics that prove round/terminal state;
- continuation/free-spin commands if they occur;
- any additional buy commands exposed by the client;
- confirmation that dynamic fields are regenerated rather than replayed.

Reference GitHub Actions run: `36371016669`.
