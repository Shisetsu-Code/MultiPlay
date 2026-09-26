from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ...models import EvidenceBundle
from .wire import available_actions


@dataclass(frozen=True, slots=True)
class ClientActionVariant:
    label: str
    options: dict[str, Any]


@dataclass(slots=True)
class ClientActionContract:
    action: str
    literal_hits: int = 0
    shape_proven: bool = False
    parameterless: bool = False
    option_fields: list[str] = field(default_factory=list)
    variants: list[ClientActionVariant] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)

    @property
    def replay_eligible(self) -> bool:
        return self.shape_proven and (self.parameterless or bool(self.variants))


def discover_client_action_contracts(
    evidence: EvidenceBundle,
) -> dict[str, ClientActionContract]:
    actions: set[str] = set()
    for exchange in evidence.http:
        actions.update(available_actions(exchange.response_body))

    bundle = "\n".join(script.text for script in evidence.scripts if script.text)
    return {
        action: _discover_action(bundle, action)
        for action in sorted(actions - {"", "init", "spin"})
    }


def _discover_action(bundle: str, action: str) -> ClientActionContract:
    contract = ClientActionContract(action=action)
    if not bundle or not action:
        return contract

    pattern = re.compile(
        r'(?:["\']?command["\']?)\s*:\s*["\']'
        + re.escape(action)
        + r'["\']'
    )
    occurrences = list(pattern.finditer(bundle))[:32]
    contract.literal_hits = len(occurrences)

    seen_variants: set[str] = set()
    for occurrence in occurrences:
        window = bundle[occurrence.end() : occurrence.end() + 900]
        direct = re.search(
            r'(?:["\']?options["\']?)\s*:\s*\{([^{}]{0,700})\}',
            window,
        )
        if direct is None:
            if re.search(
                r'(?:["\']?options["\']?)\s*:\s*[A-Za-z_$][A-Za-z0-9_$]*',
                window,
            ):
                contract.shape_proven = True
                _append_unique(contract.unresolved_fields, "<forwarded-options>")
            continue

        contract.shape_proven = True
        body = direct.group(1).strip()
        if not body:
            contract.parameterless = True
            continue

        literals, unresolved, fields = _parse_object(body)
        for field_name in fields:
            _append_unique(contract.option_fields, field_name)
        for field_name in unresolved:
            _append_unique(contract.unresolved_fields, field_name)

        if unresolved:
            continue

        label = _variant_label(literals)
        if label in seen_variants:
            continue
        seen_variants.add(label)
        contract.variants.append(ClientActionVariant(label=label, options=literals))

    return contract


def _parse_object(body: str) -> tuple[dict[str, Any], list[str], list[str]]:
    literals: dict[str, Any] = {}
    unresolved: list[str] = []
    fields: list[str] = []

    for pair in _split_pairs(body):
        match = re.match(
            r'(?:["\']?)([A-Za-z_$][A-Za-z0-9_$]*)(?:["\']?)\s*:\s*(.+)$',
            pair,
        )
        if match is None:
            continue
        key = match.group(1)
        raw = match.group(2).strip()
        _append_unique(fields, key)
        parsed, value = _parse_literal(raw)
        if parsed:
            literals[key] = value
        else:
            _append_unique(unresolved, key)
    return literals, unresolved, fields


def _split_pairs(body: str) -> list[str]:
    pairs: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    depth = 0

    for char in body:
        if quote:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
            current.append(char)
            continue
        if char in "([{":
            depth += 1
            current.append(char)
            continue
        if char in ")]}":
            depth = max(0, depth - 1)
            current.append(char)
            continue
        if char == "," and depth == 0:
            text = "".join(current).strip()
            if text:
                pairs.append(text)
            current = []
            continue
        current.append(char)

    text = "".join(current).strip()
    if text:
        pairs.append(text)
    return pairs


def _parse_literal(raw: str) -> tuple[bool, Any]:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        return True, raw[1:-1]
    lowered = raw.casefold()
    if lowered == "true":
        return True, True
    if lowered == "false":
        return True, False
    if lowered == "null":
        return True, None
    if re.fullmatch(r"-?\d+", raw):
        return True, int(raw)
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+)", raw):
        return True, float(raw)
    return False, None


def _variant_label(options: dict[str, Any]) -> str:
    if not options:
        return "__execute__"
    return "|".join(
        f"{key}={json.dumps(options[key], ensure_ascii=False, sort_keys=True)}"
        for key in sorted(options)
    )


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)
