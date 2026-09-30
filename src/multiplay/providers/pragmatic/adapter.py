from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ...models import AnalysisResult, EvidenceBundle, ProtocolContract
from .._common import (
    host_contains,
    http_endpoint_records,
    nested_values,
    scalar_action,
    successful_http,
)
from ..base import ProviderAdapter, ProviderDecision


_CONTINUATION_BY_NA = {
    "b": "doBonus",
    "c": "doCollect",
    "cb": "doCollectBonus",
    "bc": "doCollectBonus",
    "fso": "doFSOption",
    "m": "doMysteryScatter",
}
_FEATURE_FIELDS = {
    "fs",
    "fsmax",
    "fs_total",
    "fsleft",
    "fs_left",
    "fsmul",
    "rs",
    "rs_c",
    "rs_t",
    "rs_more",
    "rs_p",
    "rsc",
    "respins",
    "respin",
}
_INACTIVE = {"", "0", "0.0", "false", "null", "none"}


def _relevant(exchange: Any) -> bool:
    path = urlsplit(str(exchange.url or "")).path.casefold()
    return host_contains(exchange.url, "pragmaticplay") or "gameservice" in path


def _action(exchange: Any) -> str:
    return scalar_action(exchange.request_body, "action", "command")


def _fields(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def _feature_active(value: Any) -> bool:
    fields = _fields(value)
    for key in _FEATURE_FIELDS:
        raw = fields.get(key)
        if raw is None:
            continue
        if str(raw).strip().casefold() not in _INACTIVE:
            return True
    return False


class PragmaticProviderAdapter(ProviderAdapter):
    key = "pragmatic"
    display_name = "Pragmatic Play"

    def recognize(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> ProviderDecision:
        del contracts
        relevant = [item for item in evidence.http if _relevant(item)]
        actions = {_action(item) for item in relevant if _action(item)}

        reasons: list[str] = []
        score = 0.0
        if any(host_contains(item.url, "pragmaticplay") for item in evidence.http):
            score = max(score, 0.90)
            reasons.append("Pragmatic-owned host observed")
        if "doSpin" in actions:
            score = max(score, 0.99)
            reasons.append("Pragmatic doSpin gameService action observed")

        return ProviderDecision(
            provider=self.key,
            recognized=score >= 0.75,
            confidence=score,
            reasons=tuple(reasons),
        )

    def validate(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> list[str]:
        if not self.recognize(evidence, contracts).recognized:
            return ["Pragmatic provider identity is not demonstrated by current evidence."]

        exchanges = [item for item in evidence.http if _relevant(item)]
        actions = {
            _action(item)
            for item in exchanges
            if _action(item) and successful_http(item)
        }
        reasons: list[str] = []

        if "doSpin" not in actions:
            reasons.append("pragmatic: successful doSpin request is not demonstrated.")

        for exchange in exchanges:
            if not successful_http(exchange):
                reasons.append(
                    f"pragmatic: unsuccessful gameService request at {exchange.evidence_id}."
                )
            fields = _fields(exchange.response_body)
            na = str(fields.get("na") or "").strip().casefold()
            required = _CONTINUATION_BY_NA.get(na)
            if required and required not in actions:
                reasons.append(
                    f"pragmatic: response na={na!r} requires demonstrated {required} request."
                )

        active_spin_states = [
            item
            for item in exchanges
            if str(_fields(item.response_body).get("na") or "").strip().casefold() == "s"
            and _feature_active(item.response_body)
        ]
        spin_count = sum(
            1
            for item in exchanges
            if _action(item) == "doSpin" and successful_http(item)
        )
        if active_spin_states and spin_count < 2:
            reasons.append(
                "pragmatic: feature continuation is active but continuation doSpin is not demonstrated."
            )

        return list(dict.fromkeys(reasons))

    def endpoint_records(
        self,
        evidence: EvidenceBundle,
        analysis: AnalysisResult,
        *,
        source_ref: str,
        environment: str,
    ):
        return http_endpoint_records(
            provider=self.key,
            evidence=evidence,
            analysis=analysis,
            source_ref=source_ref,
            environment=environment,
            predicate=_relevant,
            action_of=_action,
            sensitive_keys=frozenset({"mgckey"}),
            dynamic_keys=frozenset({"index", "counter", "c", "l", "bl", "pur"}),
            notes=("Migrated from demonstrated Pragmatic gameService action contracts.",),
        )


__all__ = ["PragmaticProviderAdapter"]
