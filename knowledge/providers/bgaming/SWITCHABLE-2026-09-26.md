# BGaming switchable-container evidence — 2026-09-26

Current demo evidence was produced by the Playwright causal explorer.

No live/real-money environment was used.

## Representative selection

MultiPlay selected the current `switchable-container` runtime dynamically from the
catalog/family map.

Observed parent identifier:

    AllLuckyClover

This identifier is evidence only and is not hardcoded into provider logic.

## Causal variant switch

A real Playwright click selected a child variant and caused this sequence:

    GET /lobby/FUN/<dynamic>/launch
        ?game=AllLuckyClover100
        &from=AllLuckyClover

    HTTP 302

    GET /games/AllLuckyClover100/FUN.json
        ?launch_token=<redacted>

    HTTP 200

    POST /api/AllLuckyClover100/<id>/<session>

    {
      "command": "init",
      "extra_data": {
        "round_series_id": "<dynamic>"
      }
    }

The child init returned HTTP 200.

## Validation rule

The current runtime does not require the lobby GET itself to return a JSON object with
identifier/api/CSRF. A successful redirect/launch followed by an init for the selected
child is sufficient causal proof of the switch.

MultiPlay therefore validates switchable transitions as:

    provider-owned GET with dynamic game/from
    -> successful response
    -> selected child init

The ledger records the GET as:

    action: switch_variant
    method: GET
    protocol_family: switchable-container

and keeps `game` and `from` dynamic.

## Remaining work

The switch transition and child init are demonstrated.

A child base spin still needs causal browser evidence in the switched runtime before the
full switchable path is considered closed.
