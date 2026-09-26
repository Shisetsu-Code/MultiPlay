# BGaming HyperHive base-play evidence — 2026-09-26

Current demo validation was produced by the Playwright causal explorer.

No live/real-money environment was used.

## Representative selection

The representative was not hardcoded. MultiPlay selected a current game from the
catalog because its observed runtime classified as `hyperhive-jsonrpc`.

Selected runtime:

- catalog slug: `aztecs-claw-wild-dice`
- runtime family: `hyperhive-jsonrpc`
- demo host: `aztecs-claw-wild-dice.demo.bgaming-network.com`

## Causal browser evidence

The browser:

1. opened the current demo;
2. captured the visible UI;
3. discovered controls dynamically;
4. clicked the current UI through Playwright;
5. correlated each click with new network traffic.

The successful base action was click 27 in that run.

Observed causal effect:

    POST https://aztecs-claw-wild-dice.demo.bgaming-network.com/api/api

Observed request family:

    {
      "jsonrpc": "2.0",
      "method": "play",
      "id": "<dynamic>",
      "params": {
        "token": "<fresh/redacted>",
        "req": {
          "bet": 2500,
          "bet_type": "bet"
        }
      }
    }

The request was not reconstructed from game JavaScript. It was captured from the browser
request caused by the real click.

## Analysis result

- protocol family: `jsonrpc-2.0`
- provider family: `hyperhive-jsonrpc`
- status: `WIRE_COMPLETE`
- provider blockers: none

The sanitized ledger keeps:

    rpc:init
    rpc:play
    rpc:play:base

Dynamic fields include the JSON-RPC id, token and bet. The literal
`bet_type="bet"` remains part of the demonstrated successful wire.

## Remaining HyperHive work

Base play is closed for the demonstrated current shape.

Still required only when current runtime evidence exposes them:

- state_lock variants;
- custom_req variants;
- purchased_feature / feature-buy variants;
- continuation actions;
- finite/dynamic choices.

Those branches must also be obtained through real browser actions and observed requests.
