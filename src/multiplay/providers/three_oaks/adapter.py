from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ...models import AnalysisResult, EvidenceBundle, ProtocolContract
from .._common import (
    host_contains,
    http_endpoint_records,
    scalar_action,
    successful_http,
)
from ..base import ProviderAdapter, ProviderDecision


_PLAY_PATH_RE = re.compile(r"/api/v1/games/[^/]+/play/?$", re.IGNORECASE)


def _relevant(exchange: Any) -> bool:
    path = urlsplit(str(exchange.url or "")).path
    return bool(_PLAY_PATH_RE.search(path))


def _action(exchange: Any) -> str:
    return scalar_action(exchange.request_body, "command", "action")


class ThreeOaksProviderAdapter(ProviderAdapter):
    key = "3oaks"
    display_name = "3 Oaks Gaming"

    def recognize(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> ProviderDecision:
        del contracts
        reasons: list[str] = []
        score = 0.0
        if any(host_contains(item.url, "3oaks") for item in evidence.http):
            score = max(score, 0.88)
            reasons.append("3 Oaks host observed")
        if any(_relevant(item) for item in evidence.http):
            score = max(score, 0.98)
            reasons.append("/api/v1/games/<slug>/play transport observed")

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
            return ["3 Oaks provider identity is not demonstrated by current evidence."]

        plays = [item for item in evidence.http if _relevant(item)]
        successful = [item for item in plays if successful_http(item)]
        actions = {_action(item).casefold() for item in successful if _action(item)}
        reasons: list[str] = []

        if "spin" not in actions:
            reasons.append("3oaks: successful command=spin request is not demonstrated.")

        for exchange in plays:
            action = _action(exchange).casefold()
            if not successful_http(exchange):
                reasons.append(
                    f"3oaks: unsuccessful play request at {exchange.evidence_id}."
                )
            if action == "purchased_feature":
                body = exchange.request_body
                options = body.get("options") if isinstance(body, dict) else None
                if not isinstance(options, dict) or not options:
                    reasons.append(
                        "3oaks: purchased_feature request has no demonstrated options object."
                    )
            elif action and action not in {"spin", "purchased_feature"}:
                reasons.append(f"3oaks: unknown demonstrated command {action!r}.")

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
            sensitive_keys=frozenset({"token", "session", "key"}),
            dynamic_keys=frozenset({"bet", "stake"}),
            notes=(
                "3 Oaks /api/v1/games/<slug>/play contract migrated from historical captures.",
                "Purchase variants are accepted only when their options object is observed.",
            ),
        )


__all__ = ["ThreeOaksProviderAdapter"]
