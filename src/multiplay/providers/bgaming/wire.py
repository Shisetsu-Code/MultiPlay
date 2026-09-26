from __future__ import annotations

from typing import Any

from ...models import EvidenceBundle


def is_bgaming_host(host: str) -> bool:
    host = str(host or "").casefold()
    return host == "bgaming-network.com" or host.endswith(".bgaming-network.com")


def is_jsonrpc_bgaming_shape(body: Any) -> bool:
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return False
    method = str(body.get("method") or "")
    if method not in {"init", "play"}:
        return False
    params = body.get("params")
    if not isinstance(params, dict):
        return False
    if method == "init":
        return "token" in params
    req = params.get("req")
    return isinstance(req, dict) and "bet" in req


def is_api_v2_command(body: Any) -> bool:
    return (
        isinstance(body, dict)
        and isinstance(body.get("command"), str)
        and isinstance(body.get("extra_data"), dict)
    )


def is_api_v2_response(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    options = body.get("options")
    return isinstance(options, dict) and any(
        key in body for key in ("flow", "outcome", "balance", "game", "features")
    )


def is_legacy_init(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    options = body.get("options")
    return (
        isinstance(options, dict)
        and isinstance(options.get("line_bets"), list)
        and bool(options.get("line_bets"))
        and isinstance(options.get("lines"), list)
        and bool(options.get("lines"))
    )


def is_switchable_init(body: Any) -> bool:
    return (
        isinstance(body, dict)
        and not isinstance(body.get("options"), dict)
        and _number(body.get("wallet"))
        and _number(body.get("game"))
    )


def available_actions(body: Any) -> set[str]:
    if not isinstance(body, dict):
        return set()
    flow = body.get("flow")
    if not isinstance(flow, dict):
        return set()
    actions = flow.get("available_actions")
    if not isinstance(actions, list):
        return set()
    return {
        str(item).strip()
        for item in actions
        if isinstance(item, (str, int, float)) and not isinstance(item, bool)
    }


def evidence_contains_key(evidence: EvidenceBundle, key: str) -> bool:
    target = str(key).casefold()
    for script in evidence.scripts:
        if target in script.text.casefold():
            return True
    for exchange in evidence.http:
        if mapping_contains_key(exchange.request_body, target):
            return True
        if mapping_contains_key(exchange.response_body, target):
            return True
    return False


def mapping_contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return any(
            str(current).casefold() == key or mapping_contains_key(child, key)
            for current, child in value.items()
        )
    if isinstance(value, list):
        return any(mapping_contains_key(item, key) for item in value)
    return False


def provider_error(body: Any, code: int) -> bool:
    if isinstance(body, dict):
        for key, value in body.items():
            if str(key).casefold() in {"code", "error_code", "errorcode"}:
                try:
                    if int(value) == code:
                        return True
                except (TypeError, ValueError):
                    pass
            if provider_error(value, code):
                return True
    elif isinstance(body, list):
        return any(provider_error(item, code) for item in body)
    return False


def line_bet_payload(body: Any, line_count: int) -> bool:
    if not isinstance(body, dict):
        return False
    options = body.get("options")
    if not isinstance(options, dict):
        return False
    lines = options.get("lines")
    if not isinstance(lines, dict) or line_count <= 0:
        return False
    return {str(index) for index in range(line_count)} == {str(key) for key in lines}


def purchase_request(body: Any) -> bool:
    if not isinstance(body, dict) or str(body.get("command") or "") != "spin":
        return False
    options = body.get("options")
    return isinstance(options, dict) and bool(options.get("purchased_feature"))


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
