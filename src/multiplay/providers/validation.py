from __future__ import annotations

from multiplay.models import AnalysisResult, AnalysisStatus, EvidenceBundle

from .base import ProviderAdapter


def apply_provider_validation(
    analysis: AnalysisResult,
    evidence: EvidenceBundle,
    adapter: ProviderAdapter,
) -> list[str]:
    """Apply provider semantic gates after structural protocol analysis.

    Structural WIRE_COMPLETE is never sufficient when a provider adapter has
    unresolved semantic branches or an unproven provider identity.
    """
    blockers = adapter.validate(evidence, analysis.contracts)
    if blockers:
        analysis.status = AnalysisStatus.PARTIAL_REQUIRES_REVIEW
        analysis.reasons = list(dict.fromkeys([*analysis.reasons, *blockers]))
    return blockers
