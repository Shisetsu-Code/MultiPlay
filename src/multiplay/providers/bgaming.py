from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .base import ProviderAdapter, ProviderDecision
from ..models import EvidenceBundle, ProtocolContract


API_V2 = "api-v2"
LEGACY_LINES = "legacy-lines"
HYPERHIVE_JSONRPC = "hyperhive-jsonrpc"
SWITCHABLE_CONTAINER = "switchable-container"
UNKNOWN = "unknown"

# These contracts come from previously demonstrated BGaming client/runtime evidence.
# They are semantic guards only. A command is executable only when current evidence
# also advertises/demonstrates the corresponding wire shape.
KNOWN_API_V2_COMMANDS = frozenset(
    {
        "init",
        "spin",
        "freespin",
        "respin",
        "play_bonus",
        "preselection_game",
        "play_preselection_game",
        "close",
        "select_bonus",
        "buy_extra_bonus",
    }
)

CHOICE_COMMAND_FIELDS = {
    "select_bonus": "name",
    "buy_extra_bonus": "bonus_type",
}


@dataclass(frozen=True, slots=True)
class BGamingClassification:
    family: str
    confidence: float
    evidence: tuple[str, ...] = ()


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
        if any(_is_bgaming_host(host) for host in hosts):
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
            and any(_jsonrpc_bgaming_shape(x.request_body) for x in evidence.http)
        ):
            score = max(score, 0.98)
            reasons.append("BGaming-compatible JSON-RPC play/init envelope")

        recognized = score >= 0.75
        return ProviderDecision(
            provider=self.key,
            recognized=recognized,
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

        classifications = classify_bgaming(evidence)
        families = {item.family for item in classifications if item.family != UNKNOWN}
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

        return _dedupe(reasons)


def classify_bgaming(evidence: EvidenceBundle) -> list[BGamingClassification]:
    found: list[BGamingClassification] = []

    hyperhive_reasons: list[str] = []
    for exchange in evidence.http:
        body = exchange.request_body
        if _jsonrpc_bgaming_shape(body):
            hyperhive_reasons.append(f"{exchange.evidence_id}:jsonrpc")
        path = urlsplit(exchange.url).path.casefold()
        if path.endswith("/hyperhive"):
            hyperhive_reasons.append(f"{exchange.evidence_id}:hyperhive-path")
    if any("jsonrpc" in script.text.casefold() and "state_lock" in script.text for script in evidence.scripts):
        hyperhive_reasons.append("script:jsonrpc+state_lock")
    if hyperhive_reasons:
        found.append(
            BGamingClassification(
                HYPERHIVE_JSONRPC,
                1.0 if any(":jsonrpc" in reason for reason in hyperhive_reasons) else 0.82,
                tuple(_dedupe(hyperhive_reasons)),
            )
        )

    legacy_reasons: list[str] = []
    for exchange in evidence.http:
        response = exchange.response_body
        if _is_legacy_init(response):
            legacy_reasons.append(f"{exchange.evidence_id}:options.line_bets+lines")
    if legacy_reasons:
        found.append(
            BGamingClassification(
                LEGACY_LINES,
                1.0,
                tuple(legacy_reasons),
            )
        )

    switch_reasons: list[str] = []
    has_lobby_hint = _evidence_contains_text(evidence, "lobby_launch_url")
    for exchange in evidence.http:
        if _is_switchable_init(exchange.response_body):
            switch_reasons.append(f"{exchange.evidence_id}:wallet+game-no-options")
    if switch_reasons and has_lobby_hint:
        switch_reasons.append("bootstrap:lobby_launch_url")
        found.append(
            BGamingClassification(
                SWITCHABLE_CONTAINER,
                1.0,
                tuple(_dedupe(switch_reasons)),
            )
        )

    api_reasons: list[str] = []
    for exchange in evidence.http:
        request = exchange.request_body
        response = exchange.response_body
        if _is_api_v2_command(request):
            api_reasons.append(f"{exchange.evidence_id}:command-envelope")
        if _is_api_v2_response(response):
            api_reasons.append(f"{exchange.evidence_id}:options/flow/outcome")
    if api_reasons and not legacy_reasons:
        found.append(
            BGamingClassification(
                API_V2,
                1.0 if any("command-envelope" in x for x in api_reasons) else 0.88,
                tuple(_dedupe(api_reasons)),
            )
        )

    # A switchable lobby may bootstrap through the generic API-v2 envelope before
    # switching variants. Preserve both observations instead of forcing one winner.
    return sorted(found, key=lambda item: item.confidence, reverse=True)


def _validate_api_v2(evidence: EvidenceBundle) -> list[str]:
    reasons: list[str] = []
    command_requests = [
        exchange
        for exchange in evidence.http
        if _is_api_v2_command(exchange.request_body)
    ]
    if not command_requests:
        reasons.append("api-v2: no demonstrated command request.")
        return reasons

    observed_commands = {
        str(exchange.request_body.get("command") or "")
        for exchange in command_requests
        if isinstance(exchange.request_body, dict)
    }
    if "spin" not in observed_commands:
        reasons.append("api-v2: base spin wire is not demonstrated.")

    advertised: set[str] = set()
    for exchange in evidence.http:
        advertised.update(_available_actions(exchange.response_body))

    for action in sorted(advertised - {"", "init", "spin"}):
        if action not in KNOWN_API_V2_COMMANDS:
            reasons.append(f"api-v2: unknown advertised action {action!r}.")
            continue
        if action in CHOICE_COMMAND_FIELDS:
            if not _choice_wire_observed(command_requests, action, CHOICE_COMMAND_FIELDS[action]):
                reasons.append(
                    f"api-v2: choice action {action!r} advertised but its option field "
                    f"{CHOICE_COMMAND_FIELDS[action]!r} is not demonstrated in a request."
                )
        elif action not in observed_commands:
            reasons.append(
                f"api-v2: continuation {action!r} advertised but no request demonstrates it."
            )

    if _evidence_contains_text(evidence, "additionalSpinOptions"):
        purchase_requests = [
            exchange
            for exchange in command_requests
            if _purchase_request(exchange.request_body)
        ]
        if not purchase_requests:
            reasons.append(
                "api-v2: purchase selectors are advertised by client evidence but no "
                "purchase request is demonstrated."
            )

    for exchange in evidence.http:
        if _provider_error(exchange.response_body, 51100):
            reasons.append(f"api-v2: provider error 51100 at {exchange.evidence_id}.")
        if exchange.response_status == 422:
            reasons.append(f"api-v2: HTTP 422 at {exchange.evidence_id} requires branch review.")

    return reasons


def _validate_legacy_lines(evidence: EvidenceBundle) -> list[str]:
    reasons: list[str] = []
    init = next(
        (x.response_body for x in evidence.http if _is_legacy_init(x.response_body)),
        None,
    )
    if not isinstance(init, dict):
        return ["legacy-lines: init with options.line_bets/lines is missing."]

    lines = ((init.get("options") or {}).get("lines") if isinstance(init.get("options"), dict) else None)
    line_count = len(lines) if isinstance(lines, list) else 0
    if line_count <= 0:
        reasons.append("legacy-lines: line count is unresolved.")

    spins = [
        x
        for x in evidence.http
        if isinstance(x.request_body, dict)
        and str(x.request_body.get("command") or "") == "spin"
    ]
    if not spins:
        reasons.append("legacy-lines: spin request is not demonstrated.")
        return reasons

    if not any(_line_bet_payload(x.request_body, line_count) for x in spins):
        reasons.append("legacy-lines: complete per-line wager payload is not demonstrated.")

    return reasons


def _validate_hyperhive(evidence: EvidenceBundle) -> list[str]:
    reasons: list[str] = []
    rpc = [
        x
        for x in evidence.http
        if isinstance(x.request_body, dict)
        and x.request_body.get("jsonrpc") == "2.0"
    ]
    init = [x for x in rpc if str(x.request_body.get("method") or "") == "init"]
    plays = [x for x in rpc if str(x.request_body.get("method") or "") == "play"]

    if not init:
        reasons.append("hyperhive-jsonrpc: init request is not demonstrated.")
    if not plays:
        reasons.append("hyperhive-jsonrpc: play request is not demonstrated.")
        return reasons

    for exchange in plays:
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

        if _provider_error(exchange.response_body, 51100):
            reasons.append(
                f"hyperhive-jsonrpc: provider error 51100 at {exchange.evidence_id}; "
                "preserve exact wager/state_lock/custom_req serialization."
            )

    purchase_literals = _purchase_literals(evidence)
    observed_purchase = any(
        isinstance((x.request_body.get("params") or {}).get("req"), dict)
        and bool((x.request_body.get("params") or {}).get("req", {}).get("purchased_feature"))
        for x in plays
    )
    if purchase_literals and not observed_purchase:
        reasons.append(
            "hyperhive-jsonrpc: purchased_feature appears in current client evidence but "
            "no successful play request demonstrates the purchase wire."
        )

    return reasons


def _validate_switchable(evidence: EvidenceBundle) -> list[str]:
    reasons: list[str] = []
    if not _evidence_contains_text(evidence, "lobby_launch_url"):
        reasons.append("switchable-container: lobby_launch_url is not demonstrated.")

    switch_exchange = False
    for exchange in evidence.http:
        body = exchange.response_body
        if not isinstance(body, dict):
            continue
        if (
            isinstance(body.get("identifier"), str)
            and body.get("api")
            and body.get("csrfTokenHeaderName")
        ):
            request_path = urlsplit(exchange.url).path.casefold()
            if "lobby" in request_path or "switch" in request_path:
                switch_exchange = True
                break
    if not switch_exchange:
        reasons.append(
            "switchable-container: variant switch response (identifier/api/CSRF) is not demonstrated."
        )
    return reasons


def _is_bgaming_host(host: str) -> bool:
    return host == "bgaming-network.com" or host.endswith(".bgaming-network.com")


def _jsonrpc_bgaming_shape(body: Any) -> bool:
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


def _is_api_v2_command(body: Any) -> bool:
    return (
        isinstance(body, dict)
        and isinstance(body.get("command"), str)
        and isinstance(body.get("extra_data"), dict)
    )


def _is_api_v2_response(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    options = body.get("options")
    return isinstance(options, dict) and any(
        key in body for key in ("flow", "outcome", "balance", "game", "features")
    )


def _is_legacy_init(body: Any) -> bool:
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


def _is_switchable_init(body: Any) -> bool:
    return (
        isinstance(body, dict)
        and not isinstance(body.get("options"), dict)
        and isinstance(body.get("wallet"), (int, float))
        and not isinstance(body.get("wallet"), bool)
        and isinstance(body.get("game"), (int, float))
        and not isinstance(body.get("game"), bool)
    )


def _available_actions(body: Any) -> set[str]:
    if not isinstance(body, dict):
        return set()
    flow = body.get("flow")
    if not isinstance(flow, dict):
        return set()
    actions = flow.get("available_actions")
    if not isinstance(actions, list):
        return set()
    return {
        str(action).strip()
        for action in actions
        if isinstance(action, (str, int, float)) and not isinstance(action, bool)
    }


def _choice_wire_observed(exchanges: list[Any], command: str, field: str) -> bool:
    for exchange in exchanges:
        body = exchange.request_body
        if not isinstance(body, dict) or str(body.get("command") or "") != command:
            continue
        options = body.get("options")
        if isinstance(options, dict) and field in options:
            return True
    return False


def _purchase_request(body: Any) -> bool:
    if not isinstance(body, dict) or str(body.get("command") or "") != "spin":
        return False
    options = body.get("options")
    if not isinstance(options, dict):
        return False
    return bool(options.get("purchased_feature"))


def _line_bet_payload(body: Any, line_count: int) -> bool:
    if not isinstance(body, dict):
        return False
    options = body.get("options")
    if not isinstance(options, dict):
        return False
    lines = options.get("lines")
    if not isinstance(lines, dict) or line_count <= 0:
        return False
    return {str(i) for i in range(line_count)} == {str(key) for key in lines}


def _purchase_literals(evidence: EvidenceBundle) -> set[str]:
    values: set[str] = set()
    marker = "purchased_feature"
    for script in evidence.scripts:
        text = script.text
        if marker not in text:
            continue
        # Do not infer executable values here. Presence only creates a review gate.
        values.add(marker)
    return values


def _provider_error(body: Any, code: int) -> bool:
    if isinstance(body, dict):
        for key, value in body.items():
            if str(key).casefold() in {"code", "error_code", "errorcode"}:
                try:
                    if int(value) == code:
                        return True
                except (TypeError, ValueError):
                    pass
            if _provider_error(value, code):
                return True
    elif isinstance(body, list):
        return any(_provider_error(item, code) for item in body)
    return False


def _evidence_contains_text(evidence: EvidenceBundle, needle: str) -> bool:
    target = needle.casefold()
    for script in evidence.scripts:
        if target in script.text.casefold():
            return True
    for exchange in evidence.http:
        for value in (exchange.request_body, exchange.response_body):
            if isinstance(value, str) and target in value.casefold():
                return True
            if isinstance(value, dict) and _mapping_contains_key(value, target):
                return True
    return False


def _mapping_contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        for current, child in value.items():
            if str(current).casefold() == key:
                return True
            if _mapping_contains_key(child, key):
                return True
    elif isinstance(value, list):
        return any(_mapping_contains_key(item, key) for item in value)
    return False


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
