# BGaming migration state

This file records what is already demonstrated by the previous BGaming work and what must
still be revalidated in MultiPlay. Historical facts are not automatically promoted to a
current endpoint ledger.

## Historical provider families

Evidence-backed families already encountered:

- `api-v2`
- `legacy-lines`
- `hyperhive-jsonrpc`
- `switchable-container`

Runtime classification is structural. Game title/slug must never choose the family.

## API-v2

Historical bootstrap:

    HTML -> window.__OPTIONS__ -> api/identifier/CSRF -> init

Historical game endpoint shape:

    /api/<Game>/<id>/<session>

Observed command envelope:

    {
      "command": "<command>",
      "options": { ... },          // when required
      "extra_data": {
        "round_series_id": "<dynamic>",
        ...
      }
    }

Observed provider-level continuation vocabulary includes:

- freespin
- respin
- play_bonus
- preselection_game
- play_preselection_game
- close

Observed finite-choice contracts include:

- select_bonus with options.name, domain sourced from
  game.freespin_params.variants
- buy_extra_bonus with options.bonus_type, domain/pricing sourced from
  features.bonus_data.bonus_game_prices

Purchases observed historically use normal spin plus demonstrated selectors such as:

- purchased_feature
- purchased_feature_level (only when demonstrated)

Client-side `additionalSpinOptions` is discovery evidence, not proof that a particular
purchase request is executable.

## HyperHive JSON-RPC

Observed endpoint family:

    POST /api

Observed envelope:

    {
      "id": "<observed serializer shape>",
      "jsonrpc": "2.0",
      "method": "init|play",
      "params": { ... }
    }

For play:

    params.token          fresh per session
    params.req.bet        exact observed JSON scalar/type
    params.req.bet_type   only when demonstrated
    params.req.custom_req only when demonstrated
    params.state_lock     preserve field presence/shape; use live value only

Historical wire-fidelity work proved that normalizing the wager, dropping an empty
state_lock, discarding params extras or rebuilding only params.req can change the accepted
wire and produce provider error 51100.

Never replay captured token/state_lock values.

## Legacy line-bet

Recognized from init options containing both:

- line_bets
- lines

A demonstrated spin must preserve the complete per-line wager mapping. Optional gambling
states are not entered automatically. A demonstrated non-wagering finish path may close a
round.

## Switchable container

Historical recognition:

- init has top-level numeric wallet/game and no options object
- bootstrap contains lobby_launch_url

The container discovers child identifiers from current client evidence, switches through
the lobby endpoint, receives fresh identifier/api/CSRF data and then runs the child runtime.

Do not hardcode child identifiers.

## Dynamic picker work

Later BGaming exhaustive-path work added provider-guided dynamic index discovery.

Important rules retained:

- the picker must be advertised by current flow.available_actions/client setup evidence;
- dynamic indexes are not guessed from UI size;
- probe fresh sessions;
- accepted indexes form a demonstrated contiguous domain;
- require repeated rejection at the first boundary before closing the domain;
- historical Alice evidence resolved indexes 0..15 with 16 rejected;
- `pick_cards {mode:"any", index:<n>}` was observed in that work.

This mechanism is migration evidence. MultiPlay must not make it a default generic command
until a current BGaming capture demonstrates the corresponding action/setup wire.

## Known incomplete historical evidence

The Play-Ci sweep covered 215 BGaming catalogue games but the old complete run left all
215 at REQUIRES_REVIEW. At least 149 exposed useful bootstrap/API structures, but the
complete run predated later JSON-RPC/legacy/canonical-demo fixes.

Repeated HAR captures were bootstrap-only/network-only for some games, so no actual spin or
purchase request existed to validate.

Historical unresolved examples included:

- purchase entry accepted but continuation returned HTTP 400 in some games;
- provider error 51100 for an incorrectly reconstructed HyperHive wire;
- selectable branches where client evidence existed but runtime request was absent.

## MultiPlay completion gate

BGaming is not complete until current MultiPlay evidence demonstrates representative
contracts for every detected family and all required executable branches are either covered
or explicitly unresolved.

When complete, write:

    knowledge/providers/bgaming/endpoints.json
    knowledge/providers/bgaming/status.json

Demo and live validation remain independent.
