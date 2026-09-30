from __future__ import annotations  # noqa: I001

import json
from typing import Any
from urllib.parse import urlsplit

from ...endpoints import sanitize_endpoint_url
from ...models import (
    AnalysisResult,
    EndpointRecord,
    EvidenceBundle,
    ProtocolContract,
    ValidationState,
)
from .._common import nested_values, template_value
from ..base import ProviderAdapter, ProviderDecision


_ACTIVE_FEATURE_STATES = {5, 6, 11, 12}


def _provider_frame(frame: Any) -> bool:
    host = (urlsplit(str(frame.url or "")).hostname or "").casefold()
    return "1spin4win" in host


def _decode(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    text = str(payload or "")
    if not text.startswith("A/u2"):
        return None
    try:
        decoded = json.loads(text[4:])
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _message_type(frame: Any) -> str:
    payload = _decode(frame.payload)
    return str(payload.get("type") or "") if payload is not None else ""


def _feature_state(payload: dict[str, Any]) -> int | None:
    for raw in nested_values(payload, "st"):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        return value
    return None


class OneSpin4WinProviderAdapter(ProviderAdapter):
    key = "one_spin4win"
    display_name = "1Spin4Win / D1"

    def recognize(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> ProviderDecision:
        del contracts
        frames = [frame for frame in evidence.websocket if _provider_frame(frame)]
        decoded = [_decode(frame.payload) for frame in frames]
        reasons: list[str] = []
        score = 0.0

        if frames:
            score = max(score, 0.90)
            reasons.append("1spin4win WebSocket host observed")
        if any(item is not None for item in decoded):
            score = max(score, 0.99)
            reasons.append("A/u2 framed protocol observed")

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
            return ["1spin4win provider identity is not demonstrated by current evidence."]

        frames = sorted(
            [frame for frame in evidence.websocket if _provider_frame(frame)],
            key=lambda frame: frame.sequence,
        )
        decoded = [(frame, _decode(frame.payload)) for frame in frames]
        decoded = [(frame, payload) for frame, payload in decoded if payload is not None]
        reasons: list[str] = []

        init_sent = any(
            frame.direction.casefold() in {"send", "sent", "out"}
            and str(payload.get("type") or "") == "0"
            and len(str(payload.get("data") or "").split(",")) >= 7
            and str(payload.get("data") or "").split(",")[2].casefold() == "freeplay"
            for frame, payload in decoded
        )
        play_sent = any(
            frame.direction.casefold() in {"send", "sent", "out"}
            and str(payload.get("type") or "") == "1"
            for frame, payload in decoded
        )
        results = [
            (frame, payload)
            for frame, payload in decoded
            if frame.direction.casefold() in {"receive", "received", "recv", "in"}
            and str(payload.get("type") or "") == "3"
        ]

        if not init_sent:
            reasons.append("1spin4win: A/u2 type=0 freeplay init is not demonstrated.")
        if not play_sent:
            reasons.append("1spin4win: outbound A/u2 type=1 gameplay request is not demonstrated.")
        if not results:
            reasons.append("1spin4win: inbound type=3 result is not demonstrated.")

        if any(
            frame.direction.casefold() in {"receive", "received", "recv", "in"}
            and str(payload.get("type") or "") == "2"
            for frame, payload in decoded
        ):
            reasons.append("1spin4win: provider type=2 error is present in evidence.")

        terminal = False
        for frame, payload in results:
            state = _feature_state(payload)
            if state in _ACTIVE_FEATURE_STATES:
                continued = any(
                    later.sequence > frame.sequence
                    and later.direction.casefold() in {"send", "sent", "out"}
                    and _message_type(later) == "1"
                    for later in frames
                )
                if not continued:
                    reasons.append(
                        f"1spin4win: feature state st={state} is active without demonstrated continuation."
                    )
            else:
                terminal = True

        if results and not terminal:
            reasons.append("1spin4win: no terminal type=3 result with inactive feature state is demonstrated.")

        return list(dict.fromkeys(reasons))

    def endpoint_records(
        self,
        evidence: EvidenceBundle,
        analysis: AnalysisResult,
        *,
        source_ref: str,
        environment: str,
    ) -> list[EndpointRecord]:
        del analysis
        frames = [frame for frame in evidence.websocket if _provider_frame(frame)]
        records: list[EndpointRecord] = []
        seen: set[tuple[str, str]] = set()

        for frame in frames:
            if frame.direction.casefold() not in {"send", "sent", "out"}:
                continue
            payload = _decode(frame.payload)
            if payload is None:
                continue
            message_type = str(payload.get("type") or "")
            if message_type not in {"0", "1"}:
                continue
            action = "init" if message_type == "0" else "play"
            endpoint = sanitize_endpoint_url(frame.url)
            key = (endpoint, action)
            if key in seen:
                continue
            seen.add(key)

            demo_state = ValidationState.OBSERVED
            live_state = ValidationState.UNKNOWN
            if environment == "live":
                live_state = ValidationState.OBSERVED

            records.append(
                EndpointRecord(
                    provider=self.key,
                    protocol_family="websocket-framed",
                    action=action,
                    transport="WEBSOCKET",
                    method=None,
                    endpoint_template=endpoint,
                    request_format={
                        "prefix": "A/u2",
                        "envelope": template_value(payload, request_side=True),
                    },
                    response_format=None,
                    evidence=[source_ref, frame.evidence_id],
                    demo_state=demo_state,
                    live_state=live_state,
                    notes=[
                        "D1 A/u2 framing migrated from demonstrated Tester-Spin captures.",
                        "type=3 is a result, not necessarily terminal while st is an active feature state.",
                    ],
                )
            )
        return records


__all__ = ["OneSpin4WinProviderAdapter"]
