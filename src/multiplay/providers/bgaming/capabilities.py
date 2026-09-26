from __future__ import annotations

from typing import Any

from ...models import EvidenceBundle


def hyperhive_init_capabilities(evidence: EvidenceBundle) -> dict[str, Any]:
    """Summarize capabilities advertised by a successful observed HyperHive init."""
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
        elif isinstance(raw, dict):
            count = len(raw)
            shape = "object"
        else:
            count = 0
            shape = type(raw).__name__ if raw is not None else "null"

        return {
            "init_observed": True,
            "has_purchases": count > 0,
            "purchase_count": count,
            "purchased_features_shape": shape,
            "default_bet_present": config.get("default_bet") is not None,
            "bet_limits_present": isinstance(config.get("bet_limits"), list),
        }

    return {
        "init_observed": False,
        "has_purchases": False,
        "purchase_count": 0,
        "purchased_features_shape": "unknown",
        "default_bet_present": False,
        "bet_limits_present": False,
    }
