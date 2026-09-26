from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from multiplay.models import AnalysisResult, EndpointRecord, EvidenceBundle, ProtocolContract


@dataclass(frozen=True, slots=True)
class ProviderDecision:
    provider: str
    recognized: bool
    confidence: float
    reasons: tuple[str, ...] = ()


class ProviderAdapter(ABC):
    """Provider-owned semantics.

    A provider adapter may consume generic structural contracts, but it must never import
    another provider adapter or reuse another provider's semantic assumptions.
    """

    key: str
    display_name: str

    @abstractmethod
    def recognize(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> ProviderDecision:
        raise NotImplementedError

    @abstractmethod
    def validate(
        self,
        evidence: EvidenceBundle,
        contracts: list[ProtocolContract],
    ) -> list[str]:
        """Return blocking reasons. Empty means provider-level wire validation passed."""
        raise NotImplementedError

    def endpoint_records(
        self,
        evidence: EvidenceBundle,
        analysis: AnalysisResult,
    ) -> list[EndpointRecord]:
        """Optional provider-specific endpoint normalization.

        The neutral endpoint store can generate structural records without this method.
        Override only when the provider has demonstrated additional semantics.
        """
        return []


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderAdapter] = {}

    def register(self, provider: ProviderAdapter) -> None:
        if provider.key in self._providers:
            raise ValueError(f"duplicate provider: {provider.key}")
        self._providers[provider.key] = provider

    def get(self, key: str) -> ProviderAdapter:
        try:
            return self._providers[key]
        except KeyError as exc:
            raise KeyError(f"provider not registered: {key}") from exc

    def all(self) -> tuple[ProviderAdapter, ...]:
        return tuple(self._providers.values())
