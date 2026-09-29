from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from ... import models
from ..base import ProviderAdapter, ProviderDecision


_PURCHASE_COMMAND_RE = re.compile(r"^BB_[A-Za-z0-9_-]+$", re.IGNORECASE)
_CORE_PLAY_FIELDS = frozenset({"gameid", "cmd", "amount", "coin"})


def is_yggdrasil_host(host: str) -> bool:
    value = str(host or "").casefold()
    return value == "yggdrasilgaming.com" or value.endswith(".yggdrasilgaming.com")


def is_yggdrasil_play_url(url: str) -> bool:
    parts = urlsplit(str(url or ""))
    if not is_yggdrasil_host(parts.hostname or ""):
        return False
    if not parts.path.rstrip("/").casefold().endswith("/game.web/service"):
        return False
    query = parse_qs(parts.query, keep_blank_values=True)
    return str((query.get("fn") or [""])[0]).casefold() == "play"


def play_command(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    value = body.get("cmd")
    return str(value or "").strip()


def is_purchase_command(command: str) -> bool:
    return bool(_PURCHASE_COMMAND_RE.fullmatch(str(command or "").strip()))


class YggdrasilProviderAdapter(ProviderAdapter):
    key = "yggdrasil"
    display_name = "Yggdrasil"

    def recognize(
        self,
        evidence: models.EvidenceBundle,
        contracts: list[models.ProtocolContract],
    ) -> ProviderDecision:
        del contracts
        hosts = {
            (urlsplit(exchange.url).hostname or "").casefold()
            for exchange in evidence.http
            if exchange.url
        }
        ygg_hosts = {host for host in hosts if is_yggdrasil_host(host)}
        plays = [
            exchange
            for exchange in evidence.http
            if exchange.method.upper() == "POST"
            and is_yggdrasil_play_url(exchange.url)
            and play_command(exchange.request_body)
        ]

        reasons: list[str] = []
        score = 0.0
        if ygg_hosts:
            score = max(score, 0.90)
            reasons.append("yggdrasilgaming.com host observed")
        if plays:
            score = max(score, 0.99)
            reasons.append("game.web/service?fn=play with form cmd observed")

        return ProviderDecision(
            provider=self.key,
            recognized=score >= 0.75,
            confidence=score,
            reasons=tuple(reasons),
        )

    def validate(
        self,
        evidence: models.EvidenceBundle,
        contracts: list[models.ProtocolContract],
    ) -> list[str]:
        decision = self.recognize(evidence, contracts)
        if not decision.recognized:
            return ["Yggdrasil provider identity is not demonstrated by current evidence."]

        plays = [
            exchange
            for exchange in evidence.http
            if exchange.method.upper() == "POST"
            and is_yggdrasil_play_url(exchange.url)
            and play_command(exchange.request_body)
        ]
        if not plays:
            return ["yggdrasil: no demonstrated fn=play command request."]

        reasons: list[str] = []
        commands = {play_command(exchange.request_body) for exchange in plays}
        purchases = {command for command in commands if is_purchase_command(command)}

        for exchange in plays:
            body = exchange.request_body
            if not isinstance(body, dict):
                reasons.append(
                    f"yggdrasil: {exchange.evidence_id} request body is not a form/object mapping."
                )
                continue
            missing = sorted(_CORE_PLAY_FIELDS - set(body))
            if missing:
                reasons.append(
                    f"yggdrasil: {exchange.evidence_id} is missing demonstrated play fields "
                    + ", ".join(missing)
                    + "."
                )
            if (
                exchange.response_status is None
                or not 200 <= exchange.response_status < 400
            ):
                reasons.append(
                    f"yggdrasil: unsuccessful play response at {exchange.evidence_id}."
                )

        # Current causal evidence demonstrates two buy-bonus commands (BB_*),
        # but a buy request must never be relabelled as the base spin. Until a
        # non-purchase play command is observed, keep the provider incomplete.
        if purchases and commands == purchases:
            reasons.append(
                "yggdrasil: purchase wire is demonstrated, but base spin/play command "
                "is not demonstrated by current evidence."
            )

        return list(dict.fromkeys(reasons))

    def endpoint_records(
        self,
        evidence: models.EvidenceBundle,
        analysis: models.AnalysisResult,
        *,
        source_ref: str,
        environment: str,
    ) -> list[models.EndpointRecord]:
        del analysis
        records: list[models.EndpointRecord] = []
        seen: set[tuple[str, str]] = set()

        for exchange in evidence.http:
            if (
                exchange.method.upper() != "POST"
                or not is_yggdrasil_play_url(exchange.url)
            ):
                continue
            command = play_command(exchange.request_body)
            if not command:
                continue

            endpoint = _play_endpoint_template(exchange.url)
            key = (endpoint, command)
            if key in seen:
                continue
            seen.add(key)

            request_format = _request_template(exchange.request_body)
            response_format = _response_template(exchange.response_body)

            demo_state = models.ValidationState.OBSERVED
            live_state = models.ValidationState.UNKNOWN
            if environment == "live":
                live_state = models.ValidationState.OBSERVED

            notes = ["Yggdrasil form-encoded fn=play command observed."]
            if is_purchase_command(command):
                notes.append("Observed buy-bonus command; do not infer base spin from this request.")

            records.append(
                models.EndpointRecord(
                    provider=self.key,
                    protocol_family="http-command",
                    action=command,
                    transport="HTTP",
                    method="POST",
                    endpoint_template=endpoint,
                    request_format=request_format,
                    response_format=response_format,
                    dynamic_fields=[
                        "$.amount",
                        "$.clientinfo",
                        "$.coin",
                        "$.gameid",
                    ],
                    sensitive_fields=[
                        "$.gameHistorySessionId",
                        "$.gameHistoryTicketId",
                    ],
                    evidence=[source_ref, exchange.evidence_id],
                    demo_state=demo_state,
                    live_state=live_state,
                    notes=notes,
                )
            )

        return records


def _play_endpoint_template(url: str) -> str:
    parts = urlsplit(str(url or ""))
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            "fn=play",
            "",
        )
    )


def _request_template(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    out = dict(value)
    for key in ("gameHistorySessionId", "gameHistoryTicketId"):
        if key in out:
            out[key] = "<redacted>"
    for key in ("amount", "coin", "gameid", "clientinfo"):
        if key in out:
            out[key] = f"<dynamic:{key}>"
    return out


def _response_template(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _response_template(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_response_template(child) for child in value[:4]]
    if value is None:
        return None
    if isinstance(value, bool):
        return "<bool>"
    if isinstance(value, (int, float)):
        return "<number>"
    if isinstance(value, str):
        return "<string>"
    return f"<{type(value).__name__}>"


__all__ = [
    "YggdrasilProviderAdapter",
    "is_purchase_command",
    "is_yggdrasil_host",
    "is_yggdrasil_play_url",
    "play_command",
]
