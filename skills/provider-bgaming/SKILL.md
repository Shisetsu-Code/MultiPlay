---
name: provider-bgaming
description: >
  Contexto y reglas específicas para analizar BGaming dentro de MultiPlay,
  incluyendo api-v2, legacy-lines, hyperhive-jsonrpc, switchable-container,
  catálogo, continuaciones, choices, endpoint ledger y replay validation.
---

# BGaming / MultiPlay

Use together with:

- skills/multiplay-core/SKILL.md
- skills/provider-analysis/SKILL.md

Read first:

- knowledge/providers/bgaming/STATUS.md
- knowledge/providers/bgaming/MIGRATION.md
- knowledge/providers/bgaming/endpoints.json when present
- knowledge/providers/bgaming/status.json when present

## Runtime families

BGaming is not one protocol.

Known evidence-backed families:

- api-v2
- legacy-lines
- hyperhive-jsonrpc
- switchable-container

Classify from current runtime evidence. Never route by game title or slug.

## API-v2

Typical demonstrated envelope:

    {
      "command": "...",
      "options": {...},
      "extra_data": {
        "round_series_id": "..."
      }
    }

Do not invent commands.

Server flow.available_actions is dispatch authority.

Client serializer evidence may prove the shape of an advertised action, but a provider
analysis remains partial until the required runtime branch is demonstrated or explicitly
left unresolved.

Known historical continuations include:

- freespin
- respin
- play_bonus
- preselection_game
- play_preselection_game
- close

Known historical choice contracts include:

- select_bonus -> options.name
- buy_extra_bonus -> options.bonus_type

## HyperHive

JSON-RPC play wire is shape-sensitive.

Preserve from successful current evidence:

- req.bet JSON scalar type;
- bet_type when demonstrated;
- custom_req structure;
- purchased_feature selectors;
- params extras;
- state_lock field presence;
- current-client RPC id policy.

Never reuse captured token or non-empty state_lock.

If the observed successful wire had a non-empty state_lock, require a fresh live lock.

Provider error 51100 is evidence of wire mismatch, not a reason to guess fields.

## Legacy lines

Re-read the current line count.

A valid wager must preserve the complete options.lines mapping.

Do not enter optional gamble paths automatically.

## Switchable containers

Do not hardcode child identifiers.

Discover variants from current client/runtime evidence.

The switch operation must yield fresh:

- identifier
- api
- CSRF header information

Then analyze the selected child runtime.

## Dynamic choices

Never infer picker size visually.

For a client-proven dynamic index:

1. reach the same target in fresh sessions;
2. probe indexes from zero;
3. require accepted contiguous indexes;
4. require repeated semantic rejection at the first boundary;
5. only then consider the finite domain proven.

## Endpoint ledger

Every demonstrated endpoint/action must be stored.

BGaming endpoint records should identify semantic actions such as:

- spin
- freespin
- select_bonus
- rpc:init
- rpc:play
- switch_variant

Demo and live validation remain independent.

## Completion

Do not finalize BGaming until every detected runtime family in the current corpus has
representative successful evidence and every required executable branch is covered or
explicitly unresolved.
