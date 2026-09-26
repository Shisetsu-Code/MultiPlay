from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from ...models import EvidenceBundle
from .wire import (
    evidence_contains_key,
    is_api_v2_command,
    is_api_v2_response,
    is_jsonrpc_bgaming_shape,
    is_legacy_init,
    is_switchable_init,
)

API_V2 = "api-v2"
LEGACY_LINES = "legacy-lines"
HYPERHIVE_JSONRPC = "hyperhive-jsonrpc"
SWITCHABLE_CONTAINER = "switchable-container"
UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BGamingClassification:
    family: str
    confidence: float
    evidence: tuple[str, ...] = ()


def classify_bgaming(evidence: EvidenceBundle) -> list[BGamingClassification]:
    found: list[BGamingClassification] = []

    hyperhive: list[str] = []
    for exchange in evidence.http:
        if is_jsonrpc_bgaming_shape(exchange.request_body):
            hyperhive.append(f"{exchange.evidence_id}:jsonrpc")
        if urlsplit(exchange.url).path.casefold().endswith("/hyperhive"):
            hyperhive.append(f"{exchange.evidence_id}:hyperhive-path")
    if any(
        "jsonrpc" in script.text.casefold() and "state_lock" in script.text
        for script in evidence.scripts
    ):
        hyperhive.append("script:jsonrpc+state_lock")
    if hyperhive:
        found.append(
            BGamingClassification(
                HYPERHIVE_JSONRPC,
                1.0 if any(":jsonrpc" in item for item in hyperhive) else 0.82,
                tuple(dict.fromkeys(hyperhive)),
            )
        )

    legacy = [
        f"{exchange.evidence_id}:options.line_bets+lines"
        for exchange in evidence.http
        if is_legacy_init(exchange.response_body)
    ]
    if legacy:
        found.append(BGamingClassification(LEGACY_LINES, 1.0, tuple(legacy)))

    switchable = [
        f"{exchange.evidence_id}:wallet+game-no-options"
        for exchange in evidence.http
        if is_switchable_init(exchange.response_body)
    ]
    if switchable and evidence_contains_key(evidence, "lobby_launch_url"):
        switchable.append("bootstrap:lobby_launch_url")
        found.append(
            BGamingClassification(
                SWITCHABLE_CONTAINER,
                1.0,
                tuple(dict.fromkeys(switchable)),
            )
        )

    api: list[str] = []
    for exchange in evidence.http:
        if is_api_v2_command(exchange.request_body):
            api.append(f"{exchange.evidence_id}:command-envelope")
        if is_api_v2_response(exchange.response_body):
            api.append(f"{exchange.evidence_id}:options/flow/outcome")
    if api and not legacy:
        found.append(
            BGamingClassification(
                API_V2,
                1.0 if any("command-envelope" in item for item in api) else 0.88,
                tuple(dict.fromkeys(api)),
            )
        )

    return sorted(found, key=lambda item: item.confidence, reverse=True)
