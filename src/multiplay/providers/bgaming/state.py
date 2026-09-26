from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import EvidenceBundle, FeatureChoice, FeatureRound, FeatureSession
from .contracts import CHOICE_COMMAND_FIELDS, choice_values

ROUND_COMMANDS = frozenset({"freespin", "respin", "minispin"})
TRANSITION_COMMANDS = frozenset(
    {
        "preselection_game",
        "play_preselection_game",
        "play_bonus",
        "close",
        "collect",
        "finish",
    }
)


@dataclass(frozen=True, slots=True)
class BGamingState:
    name: str
    available_actions: tuple[str, ...]
    terminal: bool | None


def state_from_payload(payload: Any) -> BGamingState | None:
    if not isinstance(payload, dict):
        return None
    flow = payload.get("flow")
    if not isinstance(flow, dict) or not isinstance(flow.get("state"), str):
        return None

    actions_raw = flow.get("available_actions")
    actions = (
        tuple(str(item) for item in actions_raw)
        if isinstance(actions_raw, list)
        else ()
    )
    name = str(flow["state"])
    terminal = name == "closed" if "spin" in actions else None
    return BGamingState(name, actions, terminal)


def classify_command(command: str) -> str:
    command = str(command or "")
    if command in ROUND_COMMANDS:
        return "ROUND"
    if command in CHOICE_COMMAND_FIELDS:
        return "CHOICE"
    if command in TRANSITION_COMMANDS:
        return "TRANSITION"
    if command in {"init", "spin"}:
        return "BASE"
    return "UNKNOWN"


def build_feature_session(evidence: EvidenceBundle) -> FeatureSession | None:
    rounds: list[FeatureRound] = []
    choices: list[FeatureChoice] = []
    previous_response: dict[str, Any] | None = None
    feature_seen = False
    final_state: BGamingState | None = None

    for exchange in evidence.http:
        request = exchange.request_body
        response = exchange.response_body
        if not isinstance(request, dict) or not isinstance(response, dict):
            continue
        command = str(request.get("command") or "")
        if not command:
            continue

        state = state_from_payload(response)
        kind = classify_command(command)

        if command == "spin" and state is not None and state.terminal is not True:
            feature_seen = True

        if kind == "ROUND":
            feature_seen = True
            rounds.append(
                FeatureRound(
                    index=len(rounds) + 1,
                    terminal=bool(state is not None and state.terminal is True),
                )
            )

        if kind == "CHOICE":
            feature_seen = True
            field = CHOICE_COMMAND_FIELDS[command]
            options = (
                tuple(choice_values(previous_response, command))
                if isinstance(previous_response, dict)
                else ()
            )
            request_options = request.get("options")
            selected = (
                str(request_options.get(field))
                if isinstance(request_options, dict) and field in request_options
                else None
            )
            choices.append(
                FeatureChoice(
                    choice_id=command,
                    options=options,
                    selected=selected,
                    wire_field=field,
                )
            )

        if kind == "TRANSITION":
            feature_seen = True

        if state is not None:
            final_state = state
        previous_response = response

    if not feature_seen:
        return None

    if rounds and choices:
        rounds[-1].choices.extend(choices)
    elif choices:
        rounds.append(FeatureRound(index=1, choices=choices))

    return FeatureSession(
        rounds=rounds,
        terminal=bool(final_state is not None and final_state.terminal is True),
    )
