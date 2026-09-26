from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AnalysisStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    PARTIAL_REQUIRES_REVIEW = "PARTIAL_REQUIRES_REVIEW"
    WIRE_COMPLETE = "WIRE_COMPLETE"
    DEMO_VALIDATED = "DEMO_VALIDATED"
    LIVE_VALIDATED = "LIVE_VALIDATED"


class ValidationState(str, Enum):
    UNKNOWN = "UNKNOWN"
    OBSERVED = "OBSERVED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class Transport(str, Enum):
    HTTP = "HTTP"
    WEBSOCKET = "WEBSOCKET"


@dataclass(frozen=True, slots=True)
class HttpExchange:
    evidence_id: str
    method: str
    url: str
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: Any = None
    response_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: Any = None


@dataclass(frozen=True, slots=True)
class WebSocketFrame:
    evidence_id: str
    url: str
    direction: str
    payload: Any
    sequence: int


@dataclass(frozen=True, slots=True)
class ScriptEvidence:
    evidence_id: str
    source: str
    text: str


@dataclass(frozen=True, slots=True)
class UiObservation:
    evidence_id: str
    kind: str
    value: dict[str, Any]


@dataclass(slots=True)
class EvidenceBundle:
    http: list[HttpExchange] = field(default_factory=list)
    websocket: list[WebSocketFrame] = field(default_factory=list)
    scripts: list[ScriptEvidence] = field(default_factory=list)
    ui: list[UiObservation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProtocolDetection:
    family: str
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProtocolTransition:
    name: str
    family: str
    transport: Transport
    endpoint_template: str
    method: str | None
    action: str | None
    request_keys: tuple[str, ...]
    response_keys: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    deterministic: bool
    notes: tuple[str, ...] = ()


@dataclass(slots=True)
class ProtocolContract:
    family: str
    transitions: list[ProtocolTransition] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnalysisResult:
    status: AnalysisStatus
    contracts: list[ProtocolContract] = field(default_factory=list)
    provider: str | None = None
    detections: list[ProtocolDetection] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def protocol(self) -> ProtocolContract | None:
        """Compatibility convenience for single-family captures."""
        return self.contracts[0] if len(self.contracts) == 1 else None


@dataclass(frozen=True, slots=True)
class FeatureChoice:
    choice_id: str
    options: tuple[str, ...]
    selected: str | None = None
    wire_field: str | None = None


@dataclass(slots=True)
class FeatureRound:
    index: int
    choices: list[FeatureChoice] = field(default_factory=list)
    terminal: bool = False


@dataclass(slots=True)
class FeatureSession:
    session_type: str = "FEATURE_SESSION"
    rounds: list[FeatureRound] = field(default_factory=list)
    terminal: bool = False


@dataclass(slots=True)
class EndpointRecord:
    provider: str
    protocol_family: str
    action: str
    transport: str
    method: str | None
    endpoint_template: str
    request_format: dict[str, Any] | list[Any] | str | None
    response_format: dict[str, Any] | list[Any] | str | None
    dynamic_fields: list[str] = field(default_factory=list)
    sensitive_fields: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    demo_state: ValidationState = ValidationState.OBSERVED
    live_state: ValidationState = ValidationState.UNKNOWN
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["demo_state"] = self.demo_state.value
        data["live_state"] = self.live_state.value
        return data
