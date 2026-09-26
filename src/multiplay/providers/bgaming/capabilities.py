from __future__ import annotations

from typing import Any

from ...models import EvidenceBundle


def hyperhive_init_capabilities(evidence: EvidenceBundle) -> dict[str, Any]:
    """Summarize the HyperHive init protocol domain. This does not imply clickable UI controls."""
    for exchange in evidence.http:
        request = exchange.request_body
        response = exchange.response_body
        if not isinstance(request, dict) or not isinstance(response, dict):
            continue
        if request.get("jsonrpc") != "2.0" or request.get("method") != "init":
            continue

        result = response.get("result")
        if not isinstance(result, dict):
            continue
        config = result.get("config")
        if not isinstance(config, dict):
            continue

        raw = config.get("purchased_features")
        if isinstance(raw, list):
            count = len(raw)
            shape = "list"
            domain = [_safe_capability_value(item) for item in raw]
        elif isinstance(raw, dict):
            count = len(raw)
            shape = "object"
            domain = {
                str(key): _safe_capability_value(value)
                for key, value in raw.items()
            }
        else:
            count = 0
            shape = type(raw).__name__ if raw is not None else "null"
            domain = []

        return {
            "init_observed": True,
            "purchased_feature_domain_present": count > 0,
            "purchased_feature_domain_count": count,
            "purchased_feature_domain_shape": shape,
            "purchased_feature_domain": domain,
            "default_bet_present": config.get("default_bet") is not None,
            "bet_limits_present": isinstance(config.get("bet_limits"), list),
        }

    return {
        "init_observed": False,
        "purchased_feature_domain_present": False,
        "purchased_feature_domain_count": 0,
        "purchased_feature_domain_shape": "unknown",
        "purchased_feature_domain": [],
        "default_bet_present": False,
        "bet_limits_present": False,
    }



_SENSITIVE_PARTS = {
    "authorization",
    "cookie",
    "csrf",
    "password",
    "secret",
    "session",
    "token",
}


def _safe_capability_value(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            text = str(key)
            lowered = text.casefold()
            if any(marker in lowered for marker in _SENSITIVE_PARTS):
                out[text] = "<redacted>"
            else:
                out[text] = _safe_capability_value(child)
        return out
    if isinstance(value, list):
        return [_safe_capability_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"



def hyperhive_purchase_coverage(evidence: EvidenceBundle) -> dict[str, Any]:
    capabilities = hyperhive_init_capabilities(evidence)
    raw = capabilities.get("purchased_feature_domain")
    advertised, comparable = _purchase_names(raw)
    observed: set[str] = set()

    for exchange in evidence.http:
        if (
            exchange.response_status is None
            or not 200 <= exchange.response_status < 400
            or not isinstance(exchange.request_body, dict)
        ):
            continue
        payload = exchange.request_body
        if payload.get("jsonrpc") != "2.0" or payload.get("method") != "play":
            continue
        params = payload.get("params")
        req = params.get("req") if isinstance(params, dict) else None
        if not isinstance(req, dict):
            continue
        value = req.get("purchased_feature")
        if isinstance(value, str) and value.strip():
            observed.add(value.strip())

    missing = sorted(advertised - observed) if comparable else []
    unexpected = sorted(observed - advertised) if comparable and advertised else []
    return {
        "advertised_count": len(advertised),
        "advertised": sorted(advertised),
        "observed_count": len(observed),
        "observed": sorted(observed),
        "comparable": comparable,
        "missing": missing,
        "unexpected": unexpected,
        "complete": bool(comparable and advertised and not missing),
    }


def _purchase_names(value: Any) -> tuple[set[str], bool]:
    if isinstance(value, list):
        out: set[str] = set()
        comparable = True
        for item in value:
            if isinstance(item, str) and item.strip():
                out.add(item.strip())
                continue
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    out.add(name.strip())
                    continue
            comparable = False
        return out, comparable

    if isinstance(value, dict):
        names = {str(key).strip() for key in value if str(key).strip()}
        return names, True

    return set(), value in (None, [], {})
