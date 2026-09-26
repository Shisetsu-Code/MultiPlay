from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from ...models import AnalysisResult, EndpointRecord, EvidenceBundle, ProtocolContract
from ..base import ProviderAdapter, ProviderDecision
from .classify import (
    API_V2,
    HYPERHIVE_JSONRPC,
    LEGACY_LINES,
    SWITCHABLE_CONTAINER,
    UNKNOWN,
    classify_bgaming,
)
from .client_contracts import discover_client_action_contracts
from .contracts import CHOICE_COMMAND_FIELDS, KNOWN_API_V2_COMMANDS
from .wire import (
    available_actions,
    evidence_contains_key,
    is_api_v2_command,
    is_bgaming_host,
    is_jsonrpc_bgaming_shape,
    is_legacy_init,
    line_bet_payload,
    provider_error,
    purchase_request,
)


class BGamingProviderAdapter(ProviderAdapter):
    key = "bgaming"
    display_name = "BGaming"

    def recognize(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> ProviderDecision:
        reasons: list[str] = []
        score = 0.0

        hosts = {
            (urlsplit(exchange.url).hostname or "").casefold()
            for exchange in evidence.http
            if exchange.url
        }
        hosts.update(
            (urlsplit(frame.url).hostname or "").casefold()
            for frame in evidence.websocket
            if frame.url
        )
        if any(is_bgaming_host(host) for host in hosts):
            score = max(score, 0.90)
            reasons.append("bgaming-network host observed")

        classifications = classify_bgaming(evidence)
        if classifications:
            score = max(score, max(item.confidence for item in classifications))
            reasons.extend(
                f"runtime:{item.family}"
                for item in classifications
                if item.family != UNKNOWN
            )

        if (
            any(contract.family == "jsonrpc-2.0" for contract in contracts)
            and any(is_jsonrpc_bgaming_shape(item.request_body) for item in evidence.http)
        ):
            score = max(score, 0.98)
            reasons.append("BGaming-compatible JSON-RPC play/init envelope")

        return ProviderDecision(
            provider=self.key,
            recognized=score >= 0.75,
            confidence=score,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def validate(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> list[str]:
        decision = self.recognize(evidence, contracts)
        if not decision.recognized:
            return ["BGaming provider identity is not demonstrated by current evidence."]

        families = {
            item.family
            for item in classify_bgaming(evidence)
            if item.family != UNKNOWN
        }
        if not families:
            return ["BGaming runtime family is unresolved."]

        reasons: list[str] = []
        if API_V2 in families:
            reasons.extend(_validate_api_v2(evidence))
        if LEGACY_LINES in families:
            reasons.extend(_validate_legacy_lines(evidence))
        if HYPERHIVE_JSONRPC in families:
            reasons.extend(_validate_hyperhive(evidence))
        if SWITCHABLE_CONTAINER in families:
            reasons.extend(_validate_switchable(evidence))
        return list(dict.fromkeys(reasons))

    def endpoint_records(
        self,
        evidence: EvidenceBundle,
        analysis: AnalysisResult,
        *,
        source_ref: str,
        environment: str,
    ) -> list[EndpointRecord]:
        from .ledger import build_bgaming_endpoint_records

        return build_bgaming_endpoint_records(
            evidence=evidence,
            analysis=analysis,
            source_ref=source_ref,
            environment=environment,
        )


def _validate_api_v2(evidence: EvidenceBundle) -> list[str]:
    requests = [
        exchange
        for exchange in evidence.http
        if is_api_v2_command(exchange.request_body)
    ]
    if not requests:
        return ["api-v2: no demonstrated command request."]

    reasons: list[str] = []
    observed = {
        str(exchange.request_body.get("command") or "")
        for exchange in requests
        if isinstance(exchange.request_body, dict)
    }
    if "spin" not in observed:
        reasons.append("api-v2: base spin wire is not demonstrated.")

    advertised: set[str] = set()
    for exchange in evidence.http:
        advertised.update(available_actions(exchange.response_body))
    client_contracts = discover_client_action_contracts(evidence)

    for action in sorted(advertised - {"", "init", "spin"}):
        if action not in KNOWN_API_V2_COMMANDS:
            client = client_contracts.get(action)
            if client is not None and client.replay_eligible:
                reasons.append(
                    f"api-v2: action {action!r} has a client serializer contract "
                    "but no runtime request demonstrates it."
                )
            elif client is not None and client.shape_proven:
                reasons.append(
                    f"api-v2: action {action!r} client serializer has unresolved "
                    f"option fields {client.unresolved_fields!r}."
                )
            else:
                reasons.append(f"api-v2: unknown advertised action {action!r}.")
            continue
        field = CHOICE_COMMAND_FIELDS.get(action)
        if field and not _choice_wire_observed(requests, action, field):
            reasons.append(
                f"api-v2: choice action {action!r} advertised but option field "
                f"{field!r} is not demonstrated in a request."
            )
        elif not field and action not in observed:
            reasons.append(
                f"api-v2: continuation {action!r} advertised but no request demonstrates it."
            )

    if evidence_contains_key(evidence, "additionalSpinOptions") and not any(
        purchase_request(exchange.request_body) for exchange in requests
    ):
        reasons.append(
            "api-v2: purchase selectors are advertised but no purchase request is demonstrated."
        )

    for exchange in evidence.http:
        if provider_error(exchange.response_body, 51100):
            reasons.append(f"api-v2: provider error 51100 at {exchange.evidence_id}.")
        if exchange.response_status == 422:
            reasons.append(f"api-v2: HTTP 422 at {exchange.evidence_id} requires branch review.")
    return reasons


def _validate_legacy_lines(evidence: EvidenceBundle) -> list[str]:
    init = next(
        (item.response_body for item in evidence.http if is_legacy_init(item.response_body)),
        None,
    )
    if not isinstance(init, dict):
        return ["legacy-lines: init with options.line_bets/lines is missing."]

    reasons: list[str] = []
    options = init.get("options")
    lines = options.get("lines") if isinstance(options, dict) else None
    line_count = len(lines) if isinstance(lines, list) else 0
    if line_count <= 0:
        reasons.append("legacy-lines: line count is unresolved.")

    spins = [
        item
        for item in evidence.http
        if isinstance(item.request_body, dict)
        and str(item.request_body.get("command") or "") == "spin"
    ]
    if not spins:
        reasons.append("legacy-lines: spin request is not demonstrated.")
    elif not any(line_bet_payload(item.request_body, line_count) for item in spins):
        reasons.append("legacy-lines: complete per-line wager payload is not demonstrated.")
    return reasons


def _validate_hyperhive(evidence: EvidenceBundle) -> list[str]:
    rpc = [
        item
        for item in evidence.http
        if isinstance(item.request_body, dict)
        and item.request_body.get("jsonrpc") == "2.0"
    ]
    init = [item for item in rpc if str(item.request_body.get("method") or "") == "init"]
    plays = [item for item in rpc if str(item.request_body.get("method") or "") == "play"]

    reasons: list[str] = []
    if not init:
        reasons.append("hyperhive-jsonrpc: init request is not demonstrated.")
    if not plays:
        reasons.append("hyperhive-jsonrpc: play request is not demonstrated.")
        return reasons

    for exchange in plays:
        if (
            isinstance(exchange.response_body, dict)
            and exchange.response_body.get("error") not in (None, {}, [])
        ):
            reasons.append(
                f"hyperhive-jsonrpc: RPC error at {exchange.evidence_id}: "
                f"{exchange.response_body.get('error')!r}."
            )
        params = exchange.request_body.get("params")
        if not isinstance(params, dict):
            reasons.append(f"hyperhive-jsonrpc: {exchange.evidence_id} has no params object.")
            continue
        req = params.get("req")
        if not isinstance(req, dict):
            reasons.append(f"hyperhive-jsonrpc: {exchange.evidence_id} has no params.req.")
            continue
        if "bet" not in req:
            reasons.append(f"hyperhive-jsonrpc: {exchange.evidence_id} has no req.bet.")
        custom = req.get("custom_req")
        if custom is not None and not isinstance(custom, dict):
            reasons.append(
                f"hyperhive-jsonrpc: {exchange.evidence_id} custom_req shape is unresolved."
            )
        if provider_error(exchange.response_body, 51100):
            reasons.append(
                f"hyperhive-jsonrpc: provider error 51100 at {exchange.evidence_id}; "
                "preserve exact wager/state_lock/custom_req serialization."
            )

    purchase_hint = evidence_contains_key(evidence, "purchased_feature")
    purchase_observed = any(_hyperhive_purchase(item.request_body) for item in plays)
    if purchase_hint and not purchase_observed:
        reasons.append(
            "hyperhive-jsonrpc: purchased_feature appears in current evidence but no "
            "play request demonstrates the purchase wire."
        )
    return reasons


def _validate_switchable(evidence: EvidenceBundle) -> list[str]:
    reasons: list[str] = []
    if not evidence_contains_key(evidence, "lobby_launch_url"):
        reasons.append("switchable-container: lobby_launch_url is not demonstrated.")

    if not _switchable_wire_observed(evidence):
        reasons.append(
            "switchable-container: variant switch GET followed by child init is not demonstrated."
        )
    return reasons


def _switchable_wire_observed(evidence: EvidenceBundle) -> bool:
    for index, exchange in enumerate(evidence.http):
        if exchange.method.upper() != "GET":
            continue
        parsed = urlsplit(exchange.url)
        if not is_bgaming_host((parsed.hostname or "").casefold()):
            continue
        query = parse_qs(parsed.query, keep_blank_values=False)
        game = str((query.get("game") or [""])[0]).strip()
        source = str((query.get("from") or [""])[0]).strip()
        if not game or not source:
            continue
        if exchange.response_status is None or not 200 <= exchange.response_status < 400:
            continue

        body = exchange.response_body
        if (
            isinstance(body, dict)
            and isinstance(body.get("identifier"), str)
            and body.get("api")
            and body.get("csrfTokenHeaderName")
        ):
            return True

        if _child_init_after(evidence, index, game):
            return True
    return False


def _child_init_after(
    evidence: EvidenceBundle,
    switch_index: int,
    target_identifier: str,
) -> bool:
    wanted = target_identifier.casefold()
    for exchange in evidence.http[switch_index + 1 :]:
        body = exchange.request_body
        if (
            exchange.method.upper() != "POST"
            or not isinstance(body, dict)
            or str(body.get("command") or "") != "init"
        ):
            continue
        path_parts = {
            part.casefold()
            for part in urlsplit(exchange.url).path.split("/")
            if part
        }
        if wanted in path_parts:
            return True
    return False


def _choice_wire_observed(exchanges: list[Any], command: str, field: str) -> bool:
    for exchange in exchanges:
        body = exchange.request_body
        if not isinstance(body, dict) or str(body.get("command") or "") != command:
            continue
        options = body.get("options")
        if isinstance(options, dict) and field in options:
            return True
    return False


def _hyperhive_purchase(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    params = body.get("params")
    if not isinstance(params, dict):
        return False
    req = params.get("req")
    return isinstance(req, dict) and bool(req.get("purchased_feature"))
