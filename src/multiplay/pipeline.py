from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .analyzer import MultiProtocolAnalyzer
from .models import AnalysisResult, AnalysisStatus, EvidenceBundle
from .providers import apply_provider_validation, default_provider_registry
from .providers.base import ProviderAdapter, ProviderDecision


@dataclass(slots=True)
class PipelineResult:
    analysis: AnalysisResult
    provider_decision: ProviderDecision | None = None
    provider_blockers: list[str] | None = None
    provider_adapter: ProviderAdapter | None = None

    def to_dict(self) -> dict[str, Any]:
        analysis = self.analysis
        return {
            "status": analysis.status.value,
            "provider": analysis.provider,
            "provider_decision": (
                asdict(self.provider_decision)
                if self.provider_decision is not None
                else None
            ),
            "provider_blockers": list(self.provider_blockers or []),
            "detections": [asdict(item) for item in analysis.detections],
            "contracts": [
                {
                    "family": contract.family,
                    "unresolved": contract.unresolved,
                    "metadata": contract.metadata,
                    "transitions": [
                        {
                            **asdict(transition),
                            "transport": transition.transport.value,
                        }
                        for transition in contract.transitions
                    ],
                }
                for contract in analysis.contracts
            ],
            "reasons": list(analysis.reasons),
        }


def analyze_evidence(
    evidence: EvidenceBundle,
    *,
    provider: str | None = None,
) -> PipelineResult:
    analysis = MultiProtocolAnalyzer().analyze(evidence, provider=provider)
    result = PipelineResult(analysis=analysis, provider_blockers=[])

    if not provider:
        return result

    registry = default_provider_registry()
    try:
        adapter = registry.get(provider)
    except KeyError:
        blocker = f"No provider adapter is registered for {provider!r}."
        analysis.status = AnalysisStatus.PARTIAL_REQUIRES_REVIEW
        analysis.reasons = list(dict.fromkeys([*analysis.reasons, blocker]))
        result.provider_blockers = [blocker]
        return result

    result.provider_adapter = adapter
    result.provider_decision = adapter.recognize(evidence, analysis.contracts)
    result.provider_blockers = apply_provider_validation(
        analysis,
        evidence,
        adapter,
    )
    return result
