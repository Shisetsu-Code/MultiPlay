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

## Screenshot-guided causal path

The current UI visibly exposed a `BUY BONUS` control on the left side of the reels.
Opening it displayed a `BUY FREE SPINS` modal. The green confirmation control then caused
the successful JSON-RPC request above.

Observed causal sequence:

    visible BUY BONUS
      -> BUY FREE SPINS modal
      -> green confirmation
      -> POST /api
      -> purchased_feature = "buy_bonus"
      -> HTTP 200

The click coordinates are evidence from that browser run only. They are not stored as
provider semantics or replay rules.

## Coverage state

The current init advertised 9 purchase names. Current cross-game UI evidence shows that
this list is runtime capability vocabulary, not nine mandatory UI branches for every game.

Therefore a missing advertised name is not a blocker by itself. A branch becomes required
only when current UI/client evidence actually exposes it. MultiPlay still rejects an
observed `purchased_feature` value that is absent from the current init domain.

Current demonstrated purchase branch:

- `buy_bonus`: causally demonstrated from visible UI through successful HTTP 200 response.
