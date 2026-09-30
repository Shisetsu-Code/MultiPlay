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


_STATE_CONTINUATIONS = {"respin", "freespin", "minispin", "select", "pick"}
_INDEX_CONTINUATIONS = {"select", "pick"}
_KNOWN_ACTIONS = {"init", "spin", "buy_feature", *_STATE_CONTINUATIONS}


def _is_gameserver(exchange: Any) -> bool:
    path = urlsplit(str(exchange.url or "")).path.rstrip("/").casefold()
    return path.endswith("/gameserver/demo") or path.endswith("/gameserver")


def _action(exchange: Any) -> str:
    return scalar_action(exchange.request_body, "action")


def _looks_like_rubyplay(exchange: Any) -> bool:
    if not _is_gameserver(exchange):
        return False
    body = exchange.request_body
    response = exchange.response_body
    envelope = (
        isinstance(body, dict)
        and "action" in body
        and ("v_protocol" in body or "v_math" in body)
    )
    topic = (
        isinstance(response, dict)
        and str(response.get("topic") or "").startswith("gameserver/")
    )
    return envelope or topic


class RubyPlayProviderAdapter(ProviderAdapter):
    key = "rubyplay"
    display_name = "RubyPlay"

    def recognize(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> ProviderDecision:
        del contracts
        reasons: list[str] = []
        score = 0.0
        if any(host_contains(item.url, "rubyplay.com") for item in evidence.http):
            score = max(score, 0.88)
            reasons.append("RubyPlay-owned host observed")
        if any(_looks_like_rubyplay(item) for item in evidence.http):
            score = max(score, 0.99)
            reasons.append("RubyPlay gameserver action envelope observed")

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
            return ["RubyPlay provider identity is not demonstrated by current evidence."]

        exchanges = [
            item
            for item in evidence.http
            if _is_gameserver(item) and _action(item)
        ]
        successful = [item for item in exchanges if successful_http(item)]
        actions = {_action(item).casefold() for item in successful}
        reasons: list[str] = []

        if "init" not in actions:
            reasons.append("rubyplay: successful init action is not demonstrated.")
        if "spin" not in actions:
            reasons.append("rubyplay: successful spin action is not demonstrated.")

        for exchange in exchanges:
            action = _action(exchange).casefold()
            if action not in _KNOWN_ACTIONS:
                reasons.append(f"rubyplay: unknown demonstrated action {action!r}.")
            if not successful_http(exchange):
                reasons.append(
                    f"rubyplay: unsuccessful {action or 'gameserver'} request at "
                    f"{exchange.evidence_id}."
                )
                continue

            response = exchange.response_body
            if not isinstance(response, dict):
                reasons.append(f"rubyplay: {exchange.evidence_id} response is not an object.")
                continue
            if str(response.get("status") or "").casefold() != "ok":
                reasons.append(
                    f"rubyplay: {exchange.evidence_id} does not demonstrate status=ok."
                )
            expected_topic = f"gameserver/{action}"
            if str(response.get("topic") or "") != expected_topic:
                reasons.append(
                    f"rubyplay: {exchange.evidence_id} topic does not match {expected_topic!r}."
                )

            data = response.get("data")
            if not isinstance(data, dict):
                reasons.append(f"rubyplay: {exchange.evidence_id} response.data is missing.")
                continue

            if action != "init":
                request = exchange.request_body if isinstance(exchange.request_body, dict) else {}
                before = request.get("an")
                after = data.get("an")
                try:
                    if int(after) != int(before) + 1:
                        reasons.append(
                            f"rubyplay: action counter did not increment by one at "
                            f"{exchange.evidence_id}."
                        )
                except (TypeError, ValueError):
                    reasons.append(
                        f"rubyplay: action counter is unresolved at {exchange.evidence_id}."
                    )

            next_action = str(data.get("next_action") or "").strip().casefold()
            if not next_action:
                reasons.append(
                    f"rubyplay: next_action is missing at {exchange.evidence_id}."
                )
            elif next_action not in _KNOWN_ACTIONS:
                reasons.append(f"rubyplay: unknown next_action {next_action!r}.")
            elif next_action in _STATE_CONTINUATIONS and next_action not in actions:
                reasons.append(
                    f"rubyplay: next_action={next_action!r} is advertised but its request "
                    "is not demonstrated."
                )

            request = exchange.request_body if isinstance(exchange.request_body, dict) else {}
            if action in _INDEX_CONTINUATIONS:
                index = request.get("index")
                if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                    reasons.append(
                        f"rubyplay: {action} requires a demonstrated non-negative integer index."
                    )
            if action == "buy_feature":
                feature_type = str(request.get("buy_feature_type") or "").strip()
                price = request.get("buy_feature_price")
                if not feature_type:
                    reasons.append("rubyplay: buy_feature_type is not demonstrated.")
                if (
                    not isinstance(price, (int, float))
                    or isinstance(price, bool)
                    or price <= 0
                ):
                    reasons.append("rubyplay: positive buy_feature_price is not demonstrated.")

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
            predicate=lambda item: _is_gameserver(item) and bool(_action(item)),
            action_of=_action,
            sensitive_keys=frozenset({"key", "sessionkey", "token"}),
            dynamic_keys=frozenset({"an", "bet", "index", "buy_feature_price"}),
            notes=(
                "RubyPlay gameserver actions preserve action/next_action and action-number semantics.",
                "select/pick require an observed index domain; unknown choices remain partial.",
            ),
        )


__all__ = ["RubyPlayProviderAdapter"]
