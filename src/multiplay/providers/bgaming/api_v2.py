from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ...models import EvidenceBundle

_DYNAMIC_OPTION_KEYS = {"amount", "bet", "lines", "stake", "wager"}
_DYNAMIC_EXTRA_KEYS = {
    "action_id",
    "id",
    "nonce",
    "round_id",
    "round_series_id",
    "state_lock",
    "timestamp",
}
_SENSITIVE_MARKERS = {
    "authorization",
    "cookie",
    "csrf",
    "password",
    "secret",
    "session",
    "token",
}


@dataclass(frozen=True, slots=True)
class ApiV2Template:
    evidence_id: str
    command: str
    has_options: bool
    option_static: dict[str, Any] = field(default_factory=dict)
    option_dynamic_shapes: dict[str, Any] = field(default_factory=dict)
    extra_static: dict[str, Any] = field(default_factory=dict)
    extra_dynamic_shapes: dict[str, Any] = field(default_factory=dict)


def extract_api_v2_templates(evidence: EvidenceBundle) -> list[ApiV2Template]:
    templates: list[ApiV2Template] = []
    for exchange in evidence.http:
        if (
            exchange.response_status is None
            or not 200 <= exchange.response_status < 400
            or not isinstance(exchange.request_body, dict)
        ):
            continue
        body = exchange.request_body
        command = body.get("command")
        extra = body.get("extra_data")
        if not isinstance(command, str) or not isinstance(extra, dict):
            continue

        raw_options = body.get("options")
        has_options = "options" in body
        if has_options and not isinstance(raw_options, dict):
            continue
        options = raw_options if isinstance(raw_options, dict) else {}

        option_static, option_dynamic = _split_mapping(
            options,
            dynamic_keys=_DYNAMIC_OPTION_KEYS,
        )
        extra_static, extra_dynamic = _split_mapping(
            extra,
            dynamic_keys=_DYNAMIC_EXTRA_KEYS,
        )
        templates.append(
            ApiV2Template(
                evidence_id=exchange.evidence_id,
                command=command,
                has_options=has_options,
                option_static=option_static,
                option_dynamic_shapes=option_dynamic,
                extra_static=extra_static,
                extra_dynamic_shapes=extra_dynamic,
            )
        )
    return templates


def choose_api_v2_template(
    templates: list[ApiV2Template],
    *,
    command: str,
    purchased_feature: str = "",
    purchased_feature_level: str = "",
) -> ApiV2Template | None:
    wanted_command = str(command or "")
    wanted_feature = str(purchased_feature or "")
    wanted_level = str(purchased_feature_level or "")

    matches = []
    for item in templates:
        if item.command != wanted_command:
            continue
        if str(item.option_static.get("purchased_feature") or "") != wanted_feature:
            continue
        if str(item.option_static.get("purchased_feature_level") or "") != wanted_level:
            continue
        matches.append(item)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return None

    signatures = {
        (
            item.command,
            item.has_options,
            json.dumps(item.option_static, sort_keys=True, default=str),
            json.dumps(item.option_dynamic_shapes, sort_keys=True, default=str),
            json.dumps(item.extra_static, sort_keys=True, default=str),
            json.dumps(item.extra_dynamic_shapes, sort_keys=True, default=str),
        )
        for item in matches
    }
    return matches[0] if len(signatures) == 1 else None


def apply_api_v2_template(
    template: ApiV2Template,
    *,
    fresh_options: dict[str, Any] | None = None,
    fresh_extra_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options_input = dict(fresh_options or {})
    extra_input = dict(fresh_extra_data or {})

    payload: dict[str, Any] = {"command": template.command}
    if template.has_options:
        options = deepcopy(template.option_static)
        for key, expected_shape in template.option_dynamic_shapes.items():
            if key not in options_input:
                raise ValueError(f"API-v2 replay requires fresh options.{key}.")
            value = options_input[key]
            _require_shape(value, expected_shape, f"options.{key}")
            options[key] = deepcopy(value)

        unexpected = set(options_input) - set(template.option_dynamic_shapes)
        if unexpected:
            raise ValueError(
                "API-v2 fresh options contain fields not demonstrated as dynamic: "
                + ", ".join(sorted(unexpected))
            )
        payload["options"] = options
    elif options_input:
        raise ValueError("API-v2 observed request did not contain options.")

    extra = deepcopy(template.extra_static)
    for key, expected_shape in template.extra_dynamic_shapes.items():
        if key not in extra_input:
            raise ValueError(f"API-v2 replay requires fresh extra_data.{key}.")
        value = extra_input[key]
        _require_shape(value, expected_shape, f"extra_data.{key}")
        extra[key] = deepcopy(value)

    unexpected_extra = set(extra_input) - set(template.extra_dynamic_shapes)
    if unexpected_extra:
        raise ValueError(
            "API-v2 fresh extra_data contain fields not demonstrated as dynamic: "
            + ", ".join(sorted(unexpected_extra))
        )
    payload["extra_data"] = extra
    return payload


def _split_mapping(
    value: dict[str, Any],
    *,
    dynamic_keys: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    static: dict[str, Any] = {}
    dynamic: dict[str, Any] = {}
    for key, child in value.items():
        key_text = str(key)
        lowered = key_text.casefold()
        if lowered in dynamic_keys or _sensitive_key(lowered):
            dynamic[key_text] = _shape(child)
        else:
            static[key_text] = deepcopy(child)
    return static, dynamic


def _sensitive_key(lowered: str) -> bool:
    return any(marker in lowered for marker in _SENSITIVE_MARKERS)


def _shape(value: Any) -> Any:
    if isinstance(value, bool):
        return {"type": "bool"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": "null"}
    if isinstance(value, dict):
        return {
            "type": "object",
            "fields": {
                str(key): _shape(child)
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            },
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "items": [_shape(item) for item in value],
        }
    return {"type": type(value).__name__}


def _require_shape(value: Any, expected: Any, path: str) -> None:
    actual = _shape(value)
    if actual != expected:
        raise ValueError(
            f"API-v2 {path} shape differs from the observed successful wire."
        )
