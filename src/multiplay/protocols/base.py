from __future__ import annotations

from abc import ABC, abstractmethod

from multiplay.models import EvidenceBundle, ProtocolContract, ProtocolDetection


class ProtocolAdapter(ABC):
    """Structural protocol adapter.

    It may understand transport/wire structure, but must not import provider-specific
    semantics. Those belong under multiplay.providers.
    """

    family: str

    @abstractmethod
    def detect(self, evidence: EvidenceBundle) -> ProtocolDetection:
        raise NotImplementedError

    @abstractmethod
    def build(self, evidence: EvidenceBundle) -> ProtocolContract:
        raise NotImplementedError
