from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ChoiceContract:
    option_field: str
    container_path: tuple[str, ...]
    value_field: str = "name"
    mapping_keys: bool = False


@dataclass(frozen=True, slots=True)
class CommandContract:
    command: str
    states: tuple[str, ...] = ()
    choice: ChoiceContract | None = None
    source: str = "historical-provider-evidence"

    @property
    def parameterless(self) -> bool:
        return self.choice is None

    def accepts_state(self, state: str) -> bool:
        return not self.states or str(state or "") in self.states


_COMMANDS = (
    CommandContract("freespin", states=("freespins",)),
    CommandContract("respin", states=("respin",)),
    CommandContract("play_bonus", states=("play_bonus",)),
    CommandContract("preselection_game", states=("preselection_game",)),
    CommandContract("play_preselection_game", states=("preselection_game",)),
    CommandContract("close", states=("gamble",)),
    CommandContract(
        "select_bonus",
        states=("select_bonus",),
        choice=ChoiceContract(
            option_field="name",
            container_path=("game", "freespin_params", "variants"),
            value_field="name",
        ),
        source="provider-client+runtime.game.freespin_params.variants",
    ),
    CommandContract(
        "buy_extra_bonus",
        choice=ChoiceContract(
            option_field="bonus_type",
            container_path=("features", "bonus_data", "bonus_game_prices"),
            mapping_keys=True,
        ),
        source="provider-client+runtime.features.bonus_data.bonus_game_prices",
    ),
)

COMMAND_CONTRACTS = {item.command: item for item in _COMMANDS}
KNOWN_API_V2_COMMANDS = frozenset({"init", "spin", *COMMAND_CONTRACTS})
CHOICE_COMMAND_FIELDS = {
    command: contract.choice.option_field
    for command, contract in COMMAND_CONTRACTS.items()
    if contract.choice is not None
}


def command_contract(command: str) -> CommandContract | None:
    return COMMAND_CONTRACTS.get(str(command or ""))


def choice_values(data: dict[str, Any], command: str) -> list[str]:
    contract = command_contract(command)
    choice = contract.choice if contract is not None else None
    if choice is None:
        return []

    raw = _path_value(data, choice.container_path)
    if choice.mapping_keys and isinstance(raw, dict):
        return [str(key) for key in raw if str(key)]

    if isinstance(raw, dict):
        items = list(raw.values())
    elif isinstance(raw, list):
        items = raw
    else:
        return []

    values: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get(choice.value_field)
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text and text not in values:
            values.append(text)
    return values


def _path_value(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
