from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ...models import AnalysisResult, EvidenceBundle, ProtocolContract
from .._common import (
    http_endpoint_records,
    nested_values,
    successful_http,
)
from ..base import ProviderAdapter, ProviderDecision


def _leaf(exchange: Any) -> str:
    return urlsplit(str(exchange.url or "")).path.rstrip("/").rsplit("/", 1)[-1].casefold()


def _relevant(exchange: Any) -> bool:
    path = urlsplit(str(exchange.url or "")).path.rstrip("/").casefold()
    if path.endswith(("/platform/game/settings", "/platform/game/spin", "/platform/game/choice")):
        return True
    body = exchange.request_body
    return (
        isinstance(body, dict)
        and {"gameId", "sessionId"} <= set(body)
        and ("stake" in body or "roundId" in body)
    )


def _action(exchange: Any) -> str:
    leaf = _leaf(exchange)
    if leaf in {"settings", "spin", "choice"}:
        return leaf
    return "platform-game"


def _feature_buy_names(value: Any) -> set[str]:
    names: set[str] = set()
    for raw in nested_values(value, "featureBuy"):
        if isinstance(raw, str) and raw.strip():
            names.add(raw.strip())
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        names.add(name)
    return names


def _pending_choices(value: Any) -> list[set[str]]:
    out: list[set[str]] = []
    for choices in nested_values(value, "choices"):
        if not isinstance(choices, dict):
            continue
        selected = choices.get("selected")
        available = choices.get("available")
        if selected not in {None, ""} or not isinstance(available, list):
            continue
        domain = {str(item).strip() for item in available if str(item).strip()}
        if domain:
            out.append(domain)
    return out


class RedTigerProviderAdapter(ProviderAdapter):
    key = "redtiger"
    display_name = "Red Tiger"

    def recognize(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> ProviderDecision:
        del contracts
        relevant = [item for item in evidence.http if _relevant(item)]
        reasons: list[str] = []
        score = 0.0

        if any("redtiger" in str(urlsplit(item.url).hostname or "").casefold() for item in evidence.http):
            score = max(score, 0.90)
            reasons.append("Red Tiger host observed")
        if any(_leaf(item) == "spin" for item in relevant):
            score = max(score, 0.99)
            reasons.append("platform/game/spin contract observed")
        elif any(_leaf(item) == "settings" for item in relevant):
            score = max(score, 0.96)
            reasons.append("platform/game/settings contract observed")

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
            return ["Red Tiger provider identity is not demonstrated by current evidence."]

        relevant = [item for item in evidence.http if _relevant(item)]
        settings = [item for item in relevant if _action(item) == "settings"]
        spins = [item for item in relevant if _action(item) == "spin"]
        choices = [item for item in relevant if _action(item) == "choice"]
        reasons: list[str] = []

        if not settings:
            reasons.append("redtiger: platform/game/settings is not demonstrated.")
        if not any(successful_http(item) for item in spins):
            reasons.append("redtiger: successful platform/game/spin is not demonstrated.")

        for exchange in [*settings, *spins, *choices]:
            if not successful_http(exchange):
                reasons.append(
                    f"redtiger: unsuccessful {_action(exchange)} request at {exchange.evidence_id}."
                )
                continue
            response = exchange.response_body
            if isinstance(response, dict) and response.get("success") is not True:
                reasons.append(
                    f"redtiger: {_action(exchange)} response does not demonstrate success=true."
                )

        advertised_buys: set[str] = set()
        for item in settings:
            advertised_buys.update(_feature_buy_names(item.response_body))
        observed_buys: set[str] = set()
        for item in spins:
            body = item.request_body
            if not isinstance(body, dict):
                continue
            extras = body.get("extras")
            features = extras.get("features") if isinstance(extras, dict) else None
            name = str(features.get("featureBuy") or "").strip() if isinstance(features, dict) else ""
            if name:
                observed_buys.add(name)

        for name in sorted(advertised_buys - observed_buys):
            reasons.append(
                f"redtiger: advertised featureBuy {name!r} has no demonstrated spin request."
            )

        pending = [
            domain
            for item in spins
            for domain in _pending_choices(item.response_body)
        ]
        observed_choice_values = {
            str(item.request_body.get("choice") or "").strip()
            for item in choices
            if isinstance(item.request_body, dict) and successful_http(item)
        }
        for domain in pending:
            if not (domain & observed_choice_values):
                reasons.append(
                    "redtiger: server announced a choice continuation without a demonstrated "
                    f"choice request from {sorted(domain)!r}."
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
            sensitive_keys=frozenset({"token", "sessionid"}),
            dynamic_keys=frozenset({"stake", "roundid", "choice", "featurebuycost"}),
            notes=(
                "Red Tiger settings/spin/choice semantics remain provider-owned.",
                "Feature buys and choice continuations require demonstrated request branches.",
            ),
        )


__all__ = ["RedTigerProviderAdapter"]
