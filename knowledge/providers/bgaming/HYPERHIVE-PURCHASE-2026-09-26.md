# BGaming HyperHive purchase evidence — 2026-09-26

Current demo evidence was produced by the Playwright causal explorer.

No live/real-money environment was used.

## Representative selection

The representative was selected dynamically from the current catalog because:

- runtime classified as `hyperhive-jsonrpc`;
- its observed `init` advertised purchases.

Selected current runtime:

- catalog slug: `big-bucks-saloon`;
- purchase domain advertised by init: 9 entries;
- browser exploration: 64 real clicks.

The title is evidence only. It is not used by provider routing or request generation.

## Observed purchase

A real Playwright click caused:

    POST https://big-bucks-saloon.demo.bgaming-network.com/api

Observed JSON-RPC request:

    {
      "id": 0,
      "jsonrpc": "2.0",
      "method": "play",
      "params": {
        "req": {
          "bet": 40,
          "purchased_feature": "buy_bonus"
        },
        "state_lock": "<dynamic>",
        "token": "<fresh/redacted>"
      }
    }

The provider returned HTTP 200.

This request was captured from the browser. It was not reconstructed from JavaScript.

## Ledger

MultiPlay stores the observed purchase separately from base play:

- `rpc:play:base`
- `rpc:play:variant-...`

The purchase variant discriminator is:

    {"purchased_feature":"buy_bonus"}

Dynamic fields include:

- JSON-RPC id;
- bet;
- state_lock;
- token.

The literal `purchased_feature="buy_bonus"` remains part of the demonstrated wire.

## Coverage state

The current init advertised 9 purchase entries, while this run causally demonstrated one
purchase wire value.

Therefore purchase coverage is not considered complete yet.

MultiPlay now persists the advertised purchase domain and compares it against successful
Playwright-observed `purchased_feature` requests. Missing variants remain blockers.
