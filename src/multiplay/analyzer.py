from __future__ import annotations

from collections.abc import Iterable

from .models import AnalysisResult, AnalysisStatus, EvidenceBundle, ProtocolDetection
from .protocols import HttpCommandProtocol, JsonRpcProtocol, ProtocolAdapter, WebSocketProtocol


class MultiProtocolAnalyzer:
    """Detect and build every demonstrated protocol family in one evidence bundle."""

    def __init__(
        self,
        protocols: Iterable[ProtocolAdapter] | None = None,
        *,
        detection_threshold: float = 0.50,
    ) -> None:
        self.protocols = tuple(
            protocols
            or (
                JsonRpcProtocol(),
                WebSocketProtocol(),
                HttpCommandProtocol(),
            )
        )
        self.detection_threshold = float(detection_threshold)

    def analyze(self, evidence: EvidenceBundle, *, provider: str | None = None) -> AnalysisResult:
        detections = [adapter.detect(evidence) for adapter in self.protocols]
        detections.sort(key=lambda item: item.score, reverse=True)

        selected: list[tuple[ProtocolAdapter, ProtocolDetection]] = []
        for adapter, detection in zip(self.protocols, [a.detect(evidence) for a in self.protocols]):
            if detection.score >= self.detection_threshold:
                selected.append((adapter, detection))

        if not selected:
            return AnalysisResult(
                status=AnalysisStatus.PARTIAL_REQUIRES_REVIEW,
                provider=provider,
                detections=detections,
                reasons=["No protocol family reached the detection threshold."],
            )

        contracts = [adapter.build(evidence) for adapter, _ in selected]
        unresolved = _dedupe(
            reason
            for contract in contracts
            for reason in contract.unresolved
        )
        status = (
            AnalysisStatus.WIRE_COMPLETE
            if contracts and not unresolved
            else AnalysisStatus.PARTIAL_REQUIRES_REVIEW
        )
        return AnalysisResult(
            status=status,
            contracts=contracts,
            provider=provider,
            detections=detections,
            reasons=unresolved,
        )


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
