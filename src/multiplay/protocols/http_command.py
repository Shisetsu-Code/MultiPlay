from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from multiplay.models import (
    EvidenceBundle,
    ProtocolContract,
    ProtocolDetection,
    ProtocolTransition,
    Transport,
)

from .base import ProtocolAdapter

_ACTION_KEYS = ("action", "command", "cmd", "op", "operation", "event", "type", "mode", "na")


class HttpCommandProtocol(ProtocolAdapter):
    family = "http-command"

    def detect(self, evidence: EvidenceBundle) -> ProtocolDetection:
        stateful = [x for x in evidence.http if x.method not in {"GET", "HEAD", "OPTIONS"}]
        if not stateful:
            return ProtocolDetection(self.family, 0.0, ("no stateful HTTP exchange",))

        actionful = sum(1 for x in stateful if _action(x.request_body) is not None)
        score = min(0.90, 0.35 + 0.55 * (actionful / len(stateful)))
        return ProtocolDetection(
            self.family,
            score,
            (f"{actionful}/{len(stateful)} stateful requests expose an action discriminator",),
        )

    def build(self, evidence: EvidenceBundle) -> ProtocolContract:
        groups: dict[tuple[str, str, str | None], list[Any]] = defaultdict(list)
        for exchange in evidence.http:
            if exchange.method in {"GET", "HEAD", "OPTIONS"}:
                continue
            endpoint = _endpoint(exchange.url)
            groups[(exchange.method, endpoint, _action(exchange.request_body))].append(exchange)

        contract = ProtocolContract(family=self.family)
        for (method, endpoint, action), samples in sorted(groups.items()):
            req_shapes = {_shape_keys(x.request_body) for x in samples}
            resp_shapes = {_shape_keys(x.response_body) for x in samples}
            deterministic = (
                len(req_shapes) == 1
                and len(resp_shapes) == 1
                and all(x.response_status is not None and 200 <= x.response_status < 400 for x in samples)
            )
            if not deterministic:
                contract.unresolved.append(
                    f"{method} {endpoint} action={action or '<none>'}: unstable or unsuccessful evidence"
                )

            contract.transitions.append(
                ProtocolTransition(
                    name=action or endpoint.rsplit("/", 1)[-1] or "root",
                    family=self.family,
                    transport=Transport.HTTP,
                    endpoint_template=endpoint,
                    method=method,
                    action=action,
                    request_keys=_top_keys(samples[0].request_body),
                    response_keys=_top_keys(samples[0].response_body),
                    evidence_ids=tuple(x.evidence_id for x in samples),
                    deterministic=deterministic,
                )
            )

        if not contract.transitions:
            contract.unresolved.append("no stateful HTTP transitions")
        return contract


def _endpoint(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else parts.path


def _action(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    lowered = {str(k).lower(): v for k, v in body.items()}
    for key in _ACTION_KEYS:
        value = lowered.get(key)
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            return f"{key}={value}"
    return None


def _top_keys(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(sorted(str(k) for k in value))


def _shape_keys(value: Any) -> tuple[str, ...] | str:
    if isinstance(value, dict):
        return tuple(sorted(str(k) for k in value))
    if isinstance(value, list):
        return "list"
    return type(value).__name__
