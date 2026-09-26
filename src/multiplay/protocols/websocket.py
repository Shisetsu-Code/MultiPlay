from __future__ import annotations

from collections import defaultdict
from typing import Any

from multiplay.models import (
    EvidenceBundle,
    ProtocolContract,
    ProtocolDetection,
    ProtocolTransition,
    Transport,
)
from .base import ProtocolAdapter


class WebSocketProtocol(ProtocolAdapter):
    family = "websocket-framed"

    def detect(self, evidence: EvidenceBundle) -> ProtocolDetection:
        if not evidence.websocket:
            return ProtocolDetection(self.family, 0.0, ("no WebSocket frames",))
        outbound = sum(1 for frame in evidence.websocket if frame.direction.lower() in {"send", "out"})
        score = min(0.95, 0.55 + 0.05 * outbound)
        return ProtocolDetection(
            self.family,
            score,
            (f"{len(evidence.websocket)} frames, {outbound} outbound",),
        )

    def build(self, evidence: EvidenceBundle) -> ProtocolContract:
        contract = ProtocolContract(family=self.family)
        by_url: dict[str, list[Any]] = defaultdict(list)
        for frame in evidence.websocket:
            by_url[frame.url].append(frame)

        for url, frames in sorted(by_url.items()):
            outbound = [f for f in frames if f.direction.lower() in {"send", "out"}]
            inbound = [f for f in frames if f.direction.lower() in {"recv", "receive", "in"}]
            deterministic = bool(outbound and inbound)
            if not deterministic:
                contract.unresolved.append(f"{url}: missing outbound/inbound pair")

            contract.transitions.append(
                ProtocolTransition(
                    name="websocket-session",
                    family=self.family,
                    transport=Transport.WEBSOCKET,
                    endpoint_template=url,
                    method=None,
                    action=None,
                    request_keys=_payload_keys(outbound[0].payload) if outbound else (),
                    response_keys=_payload_keys(inbound[0].payload) if inbound else (),
                    evidence_ids=tuple(f.evidence_id for f in frames),
                    deterministic=deterministic,
                    notes=("provider adapter must classify frame semantics",),
                )
            )

        return contract


def _payload_keys(payload: Any) -> tuple[str, ...]:
    if isinstance(payload, dict):
        return tuple(sorted(str(k) for k in payload))
    return ()
