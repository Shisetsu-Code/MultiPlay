from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ...models import EvidenceBundle

_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "csrf",
    "password",
    "secret",
    "session",
    "token",
}


@dataclass(frozen=True, slots=True)
class HyperHiveTemplate:
    evidence_id: str
    method: str
    action: str
    purchased_feature: str
    req_static: dict[str, Any]
    bet_type_name: str
    state_lock_present: bool
    state_lock_initially_empty: bool
    params_extras: dict[str, Any] = field(default_factory=dict)


def extract_hyperhive_templates(
    evidence: EvidenceBundle,
) -> list[HyperHiveTemplate]:
    templates: list[HyperHiveTemplate] = []
    for exchange in evidence.http:
        if (
            exchange.response_status is None
            or not 200 <= exchange.response_status < 400
            or not isinstance(exchange.request_body, dict)
        ):
            continue

        response = exchange.response_body
        if (
            isinstance(response, dict)
            and response.get("error") not in (None, {}, [])
        ):
            continue

        payload = exchange.request_body
        if payload.get("jsonrpc") != "2.0" or payload.get("method") != "play":
            continue
        params = payload.get("params")
        if not isinstance(params, dict):
            continue
        req = params.get("req")
        if not isinstance(req, dict) or "bet" not in req:
            continue

        bet = req.get("bet")
        req_static = _safe_mapping(req, excluded={"bet"})
        custom = req.get("custom_req")
        action = str(req.get("action") or "")
        if isinstance(custom, dict):
            action = str(custom.get("action") or action)

        templates.append(
            HyperHiveTemplate(
                evidence_id=exchange.evidence_id,
                method="play",
                action=action,
                purchased_feature=str(req.get("purchased_feature") or ""),
                req_static=req_static,
                bet_type_name=_json_scalar_type(bet),
                state_lock_present="state_lock" in params,
                state_lock_initially_empty=params.get("state_lock") in {"", None},
                params_extras=_safe_mapping(
                    params,
                    excluded={"token", "req", "state_lock"},
                ),
            )
        )
    return templates


def choose_hyperhive_template(
    templates: list[HyperHiveTemplate],
    *,
    action: str = "",
    purchased_feature: str = "",
) -> HyperHiveTemplate | None:
    wanted_action = str(action or "")
    wanted_feature = str(purchased_feature or "")
    matches = [
        item
        for item in templates
        if item.action == wanted_action and item.purchased_feature == wanted_feature
    ]
    return matches[0] if len(matches) == 1 else None


def apply_hyperhive_template(
    fresh_params: dict[str, Any],
    template: HyperHiveTemplate,
) -> dict[str, Any]:
    out = deepcopy(fresh_params)
    token = out.get("token")
    if not isinstance(token, str) or not token:
        raise ValueError("HyperHive replay requires a fresh token.")

    fresh_req = out.get("req")
    if not isinstance(fresh_req, dict) or "bet" not in fresh_req:
        raise ValueError("HyperHive replay requires fresh req.bet.")

    bet = fresh_req["bet"]
    if _json_scalar_type(bet) != template.bet_type_name:
        raise ValueError(
            "HyperHive req.bet scalar type differs from the observed successful wire."
        )

    rebuilt = deepcopy(template.req_static)
    rebuilt["bet"] = bet

    custom = rebuilt.get("custom_req")
    if isinstance(custom, dict) and "stake" in custom:
        custom["stake"] = bet
        rebuilt["custom_req"] = custom

    out["req"] = rebuilt
    for key, value in template.params_extras.items():
        out[key] = deepcopy(value)

    if template.state_lock_present:
        live_lock = fresh_params.get("state_lock")
        if live_lock is None:
            if not template.state_lock_initially_empty:
                raise ValueError("HyperHive replay requires a fresh state_lock.")
            out["state_lock"] = ""
        else:
            out["state_lock"] = live_lock
    else:
        out.pop("state_lock", None)

    out["token"] = token
    return out


def _safe_mapping(
    value: dict[str, Any],
    *,
    excluded: set[str] | None = None,
) -> dict[str, Any]:
    excluded = set(excluded or ())
    out: dict[str, Any] = {}
    for key, child in value.items():
        key_text = str(key)
        if key_text in excluded or _sensitive_key(key_text):
            continue
        if isinstance(child, dict):
            out[key_text] = _safe_mapping(child)
        elif isinstance(child, list):
            out[key_text] = [
                _safe_value(item)
                for item in child
            ]
        else:
            out[key_text] = child
    return out


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _safe_mapping(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    return any(marker in lowered for marker in _SENSITIVE_KEYS)


def _json_scalar_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__
