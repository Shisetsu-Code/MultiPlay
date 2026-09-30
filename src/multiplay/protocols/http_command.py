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
        stateful = [
            x
            for x in evidence.http
            if x.method not in {"GET", "HEAD", "OPTIONS"} and not _is_jsonrpc(x.request_body)
        ]
        if not stateful:
            return ProtocolDetection(self.family, 0.0, ("no stateful HTTP exchange",))

        actionful = sum(1 for x in stateful if _action(x.request_body) is not None)
        endpoint_routed = sum(
            1
            for x in stateful
            if _action(x.request_body) is None and _endpoint_action(x.url)
        )
        evidence_score = (actionful + 0.75 * endpoint_routed) / len(stateful)
        score = min(0.90, 0.35 + 0.55 * evidence_score)
        return ProtocolDetection(
            self.family,
            score,
            (
                (
                    f"{actionful}/{len(stateful)} requests expose a body action; "
                    f"{endpoint_routed} use an action-like endpoint leaf"
                ),
            ),
        )

    def build(self, evidence: EvidenceBundle) -> ProtocolContract:
        groups: dict[
            tuple[str, str, str | None, tuple[Any, ...]],
            list[Any],
        ] = defaultdict(list)
        for exchange in evidence.http:
            if exchange.method in {"GET", "HEAD", "OPTIONS"} or _is_jsonrpc(exchange.request_body):
                continue
            endpoint = _endpoint(exchange.url)
            groups[
                (
                    exchange.method,
                    endpoint,
                    _action(exchange.request_body),
                    _shape_signature(exchange.request_body),
                )
            ].append(exchange)

        contract = ProtocolContract(family=self.family)
        for (method, endpoint, action, _request_shape), samples in sorted(groups.items()):
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


def _is_jsonrpc(body: Any) -> bool:
    return (
        isinstance(body, dict)
        and isinstance(body.get("method"), str)
        and ("id" in body or body.get("jsonrpc") == "2.0")
    )


def _endpoint_action(url: str) -> str | None:
    leaf = urlsplit(str(url or "")).path.rstrip("/").rsplit("/", 1)[-1].casefold()
    if leaf in {
        "spin",
        "play",
        "choice",
        "settings",
        "game",
        "start",
        "finish",
        "enter",
        "wager",
        "action",
    }:
        return leaf
    return None


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



def _shape_signature(value: Any) -> tuple[Any, ...]:
    if isinstance(value, dict):
        return (
            "object",
            tuple(
                (
                    str(key),
                    _shape_signature(child),
                )
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            ),
        )
    if isinstance(value, list):
        element_shapes = sorted(
            {
                repr(_shape_signature(item))
                for item in value[:8]
            }
        )
        return ("array", tuple(element_shapes))
    if isinstance(value, bool):
        return ("bool",)
    if isinstance(value, (int, float)):
        return ("number",)
    if isinstance(value, str):
        return ("string",)
    if value is None:
        return ("null",)
    return (type(value).__name__,)
