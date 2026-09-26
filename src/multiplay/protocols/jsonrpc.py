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


class JsonRpcProtocol(ProtocolAdapter):
    family = "jsonrpc-2.0"

    def detect(self, evidence: EvidenceBundle) -> ProtocolDetection:
        requests = [x for x in evidence.http if _rpc_request(x.request_body)]
        if not requests:
            return ProtocolDetection(self.family, 0.0, ("no JSON-RPC request",))
        explicit = sum(
            1
            for x in requests
            if isinstance(x.request_body, dict) and x.request_body.get("jsonrpc") == "2.0"
        )
        score = 0.92 if explicit else 0.82
        return ProtocolDetection(
            self.family,
            score,
            (f"{len(requests)} JSON-RPC-shaped requests; {explicit} explicitly declare 2.0",),
        )

    def build(self, evidence: EvidenceBundle) -> ProtocolContract:
        groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for exchange in evidence.http:
            if not _rpc_request(exchange.request_body):
                continue
            method = str(exchange.request_body.get("method"))
            groups[(_endpoint(exchange.url), method)].append(exchange)

        contract = ProtocolContract(family=self.family)
        for (endpoint, rpc_method), samples in sorted(groups.items()):
            param_shapes = {_top_keys((x.request_body or {}).get("params")) for x in samples}
            deterministic = (
                len(param_shapes) == 1
                and all(x.response_status is not None and 200 <= x.response_status < 400 for x in samples)
            )
            if not deterministic:
                contract.unresolved.append(
                    f"JSON-RPC {rpc_method} at {endpoint}: unstable params or unsuccessful evidence"
                )

            response = samples[0].response_body
            response_keys = _top_keys(response)
            contract.transitions.append(
                ProtocolTransition(
                    name=rpc_method,
                    family=self.family,
                    transport=Transport.HTTP,
                    endpoint_template=endpoint,
                    method="POST",
                    action=rpc_method,
                    request_keys=_top_keys((samples[0].request_body or {}).get("params")),
                    response_keys=response_keys,
                    evidence_ids=tuple(x.evidence_id for x in samples),
                    deterministic=deterministic,
                    notes=("jsonrpc request ids are dynamic",),
                )
            )

        if not contract.transitions:
            contract.unresolved.append("no JSON-RPC transitions")
        return contract


def _rpc_request(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    return isinstance(body.get("method"), str) and ("id" in body or body.get("jsonrpc") == "2.0")


def _endpoint(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else parts.path


def _top_keys(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(sorted(str(k) for k in value))
