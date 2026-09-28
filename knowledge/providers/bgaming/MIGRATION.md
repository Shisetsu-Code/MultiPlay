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

## Final Play-Ci recovery imported into MultiPlay

The later Play-Ci BGaming work used a 215-target catalogue and moved beyond the earlier
all-review sweep. It established structural handling for modern API-v2, legacy line-bet,
HyperHive JSON-RPC and the All Lucky Clovers fixed-line launcher.

The useful final JSON-RPC work is now migrated as static protocol evidence instead of
canvas/UI automation. The imported detector can recover client-declared purchase catalogs
and request fields for patterns including Yommi Rush, Sugar Mix, Big Bucks, Blazing Fire
Pots, Mystic Reels, Clash of Gods, Red Hot Chilli Chickens, Joker vs Joker, Jungle Queen,
Recycle Riches and Star Trek: The Next Generation.

Important validation boundaries retained from Play-Ci:

- Recycle Riches directly accepted the chance, buy_random and buy_max request selectors.
- Star Trek directly accepted the feature-buy flag structure. The later purchase-cost wager
  transform still requires MultiPlay runtime revalidation before it is promoted as live-safe.
- Grand Patron exposes SHOP x100, SHOP2 x250, SHOP3 x1000 and ANTE x1.3 in bet_slots, but
  its round-mode wire remains unresolved; synthetic selector guesses returned provider 51100.
- Rocket Eruption: Triple Blast and The Godfather: 3 Pillars of Power expose normal/super
  buy costs (100/200), but the exact transport selector remains unresolved.
- Sweet Samurai exposes deep_spin x100 and deep_bonanza x150, but its game-specific buy
  wire remains unresolved.
- Bling Blitz Diamond Drop, Hot Rocket and Jewel Boom showed OGA definitions without a
  game-specific feature-buy definition; Zeus Goes Wild matched a plain spin-only client.
- The final Play-Ci visual worker run added no new wire evidence for the remaining hard
  cases because their canvas startup states prevented reaching the economic controls.

Static evidence must never silently become runtime proof. MultiPlay records complete
client-declared wires as NETWORK_INFERRED pending direct demo validation, and known catalogs
without a complete serializer as CLIENT_DECLARED_WIRE_UNRESOLVED.

## Known incomplete historical evidence

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
