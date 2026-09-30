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


def _relevant(exchange: Any) -> bool:
    path = urlsplit(str(exchange.url or "")).path.rstrip("/").casefold()
    return (
        host_contains(exchange.url, "bltr-static.com", "belatragames.com")
        and path.endswith("/game")
    )


def _action(exchange: Any) -> str:
    direct = scalar_action(exchange.request_body, "action", "command")
    if direct:
        return direct

    next_phases = {str(value) for value in nested_values(exchange.response_body, "phaseNext")}
    current_phases = {str(value) for value in nested_values(exchange.response_body, "phaseCur")}
    if "toPaid" in next_phases:
        return "start"
    if "toIdle" in next_phases or "finished" in current_phases:
        return "finish"
    return "game"


class BelatraProviderAdapter(ProviderAdapter):
    key = "belatra"
    display_name = "Belatra Games"

    def recognize(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> ProviderDecision:
        del contracts
        owned = [
            item
            for item in evidence.http
            if host_contains(item.url, "bltr-static.com", "belatragames.com")
        ]
        gameplay = [item for item in owned if _relevant(item)]
        reasons: list[str] = []
        score = 0.0

        if owned:
            score = max(score, 0.90)
            reasons.append("Belatra-owned host observed")
        if gameplay:
            score = max(score, 0.98)
            reasons.append("Belatra /game transport observed")

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
            return ["Belatra provider identity is not demonstrated by current evidence."]

        gameplay = [item for item in evidence.http if _relevant(item)]
        reasons: list[str] = []
        if not gameplay:
            return ["belatra: POST /game transport is not demonstrated."]

        successful = [item for item in gameplay if successful_http(item)]
        if not successful:
            reasons.append("belatra: no successful /game request is demonstrated.")

        actions = {_action(item) for item in successful}
        explicit = {
            scalar_action(item.request_body, "action", "command")
            for item in successful
            if scalar_action(item.request_body, "action", "command")
        }
        if explicit and not {"enter", "start", "finish"} <= explicit:
            missing = sorted({"enter", "start", "finish"} - explicit)
            reasons.append(
                "belatra: explicit action flow is incomplete; missing " + ", ".join(missing) + "."
            )

        next_phases = {
            str(value)
            for item in successful
            for value in nested_values(item.response_body, "phaseNext")
        }
        current_phases = {
            str(value)
            for item in successful
            for value in nested_values(item.response_body, "phaseCur")
        }
        if "start" in actions or "finish" in actions or next_phases or current_phases:
            if "toPaid" not in next_phases:
                reasons.append("belatra: start -> phaseNext=toPaid is not demonstrated.")
            if "toIdle" not in next_phases:
                reasons.append("belatra: terminal phaseNext=toIdle is not demonstrated.")
            if "finished" not in current_phases:
                reasons.append("belatra: terminal phaseCur=finished is not demonstrated.")
        else:
            reasons.append(
                "belatra: encrypted /game traffic is present but the decrypted start/finish phase "
                "contract is not demonstrated."
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
            sensitive_keys=frozenset({"sid", "sc", "token", "session"}),
            dynamic_keys=frozenset({"bet", "stake", "counter"}),
            notes=(
                "Belatra /game transport is provider-specific and may contain encrypted request data.",
                "Completion requires the demonstrated start/toPaid then finished/toIdle phase flow.",
            ),
        )


__all__ = ["BelatraProviderAdapter"]
