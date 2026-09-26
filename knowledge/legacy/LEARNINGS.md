# Historical provider learnings

These are preserved observations from the previous projects. They are migration input,
not automatic runtime truth. Current evidence wins if it disagrees.

## Pragmatic Play

- Mature HAR-driven state-machine work existed in Tester-Spin.
- Known action families included normal spin, feature continuation, collect, free-spin
  option and mystery-scatter selection.
- Choice coverage was path-sensitive: each advertised executable branch had to be covered.
- Catalogue reconciliation distinguished authoritative provider sources from degraded DOM
  fallbacks.
- Unknown action/state values remained partial rather than being guessed.

## 1Spin4Win / D1

- Public catalogue was observed as Webflow CMS HTML.
- Runtime evidence used a game WebSocket at wss://gs.1spin4win.com:443/games.
- Historical outgoing framing included an A/u2 prefix.
- State handling followed demonstrated continuation states; previous work treated
  st={5,6,11,12} as states requiring continuation toward st=0.
- A type=3 result alone was not accepted as terminal when feature state still indicated an
  active continuation.
- Unknown states stayed partial.

## Belatra

- Public catalogue route observed: https://belatragames.com/es/games/category/2.
- Official demo pattern observed:
  https://demo.bltr-static.com/belatra/demo?game=<nickname>
- The gameplay transport observed in the historical HAR was HTTP /game rather than the
  unrelated telemetry WebSocket.
- AjaxQueue/encrypted request handling was provider-specific.
- Base-spin completion required the demonstrated start/finish state sequence; unknown
  bonus/free-spin/buy transitions remained partial.
- Multiple simultaneous demo sessions produced intermittent HTTP 500s historically, so the
  provider implementation used a default concurrency cap of one.

## BGaming

- Runtime classification was evidence-based, never based on title/slug.
- Historical runtime families:
  - api-v2
  - legacy-lines
  - hyperhive-jsonrpc
  - switchable-container
- API-v2 work used server/bootstrap options and command-style gameplay.
- HyperHive used JSON-RPC /api with init/play-style operations.
- Session token, state_lock, CSRF and launch/play tokens are ephemeral and must never be
  copied from one session into another.
- Historical wire-fidelity work preserved demonstrated bet type/value, custom_req,
  state_lock shape, RPC id behavior and extra params instead of normalizing them away.
- Purchases/features were not accepted merely because a literal existed in a bundle; an
  executable wire shape had to be demonstrated.
- Demonstrated configurable fields included purchased_feature and, for some games,
  purchased_feature_level.
- Feature cost was not inferred from a universal multiplier denominator when the provider
  did not publish one.
- Unknown choices/state remained partial.

## RubyPlay

- The historical adapter dynamically discovered launcher/session data.
- It preserved wager/pricing and action/next-action style protocol evidence.
- Only demonstrated continuations were auto-executed; a known example was respin.
- Unknown select/pick domains remained partial rather than inventing indexes.
- Catalogue/launcher ambiguity was treated conservatively.

## Red Tiger

- Historical code isolated Red Tiger under its own provider package.
- Catalogue/CMS discovery and fresh demo/bootstrap resolution were provider-owned.
- Browser settings observation could be used to obtain current runtime parameters before
  direct protocol execution.
- Purchase branches were derived from demonstrated featureBuy data.
- Result parsing walked provider result trees recursively.
- Evolution/Cloudflare launch paths historically produced HTTP 403 in some automated
  campaigns; those failures were not treated as proof that games were unsupported.

## 3 Oaks

- A minimal catalogue crawler already existed for names/thumbnails.
- Historical observed play endpoint shape:
  /api/v1/games/<game_slug>/play?lang=en
- Concrete examples previously inspected included:
  - 4_super_clover_pots
  - 4_dragon_pearls
  - coinup_volcano
  - lucky_penny_3_pots_super_wheel
- This is currently a legacy endpoint observation, not a completed MultiPlay runtime
  contract.

## Browser/network analysis lessons

- Keep browser acquisition neutral.
- Fixed deviceScaleFactor=1 simplifies coordinate-to-screenshot correlation.
- Capture network immediately around a real click to establish UI action -> request
  causality.
- For canvas/WebGL, coordinates/timing may be useful evidence, but the network exchange is
  the protocol authority.
- Prefer protocol/bootstrap discovery before exhaustive visual analysis.
