from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AnalysisResult, EndpointRecord, EvidenceBundle, ValidationState

_SENSITIVE_RE = re.compile(
    r"(?:^|_)(?:token|session|csrf|secret|password|authorization|cookie|api[_-]?key)(?:$|_)",
    re.IGNORECASE,
)
_DYNAMIC_RE = re.compile(
    r"(?:^|_)(?:id|round_id|action_id|state_lock|nonce|timestamp|bet|stake|amount|wager)(?:$|_)",
    re.IGNORECASE,
)


class ProviderKnowledgeStore:
    """Durable provider knowledge with demo/live validation kept separate."""

    def __init__(self, root: str | Path = "knowledge/providers") -> None:
        self.root = Path(root)

    def record_analysis(
        self,
        *,
        provider: str,
        analysis: AnalysisResult,
        evidence: EvidenceBundle,
        source_ref: str,
        environment: str = "demo",
    ) -> list[EndpointRecord]:
        if environment not in {"demo", "live"}:
            raise ValueError("environment must be demo or live")

        generated = _records_from_analysis(
            provider=provider,
            analysis=analysis,
            evidence=evidence,
            source_ref=source_ref,
            environment=environment,
        )
        provider_dir = self.root / provider
        provider_dir.mkdir(parents=True, exist_ok=True)
        path = provider_dir / "endpoints.json"
        merged = self._merge(path, generated)
        path.write_text(
            json.dumps([item.to_dict() for item in merged], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        run_id = _run_id(source_ref)
        runs = provider_dir / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "provider": provider,
                    "recorded_at": _now(),
                    "source_ref": source_ref,
                    "environment": environment,
                    "analysis_status": analysis.status.value,
                    "detections": [asdict(item) for item in analysis.detections],
                    "reasons": analysis.reasons,
                    "endpoint_fingerprints": [_fingerprint(item) for item in generated],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return merged

    def finalize_provider(
        self,
        *,
        provider: str,
        unresolved: list[str] | None = None,
        notes: str = "",
    ) -> Path:
        provider_dir = self.root / provider
        endpoints_path = provider_dir / "endpoints.json"
        if not endpoints_path.exists():
            raise ValueError(f"cannot finalize {provider}: no endpoint ledger")

        endpoints = json.loads(endpoints_path.read_text(encoding="utf-8"))
        if not endpoints:
            raise ValueError(f"cannot finalize {provider}: endpoint ledger is empty")

        unresolved = list(unresolved or [])
        status = {
            "provider": provider,
            "analysis_complete": not unresolved,
            "finalized_at": _now(),
            "endpoint_count": len(endpoints),
            "unresolved": unresolved,
            "notes": notes,
            "rule": (
                "analysis_complete only means the analyzed provider surface is documented; "
                "live validation remains independent per endpoint"
            ),
        }
        path = provider_dir / "status.json"
        path.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def mark_verified(
        self,
        *,
        provider: str,
        fingerprint: str,
        environment: str,
        notes: str = "",
    ) -> None:
        if environment not in {"demo", "live"}:
            raise ValueError("environment must be demo or live")
        path = self.root / provider / "endpoints.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        found = False
        for item in data:
            record = _record_from_dict(item)
            if _fingerprint(record) != fingerprint:
                continue
            item[f"{environment}_state"] = ValidationState.VERIFIED.value
            if notes:
                item.setdefault("notes", []).append(notes)
            found = True
            break
        if not found:
            raise KeyError(f"unknown endpoint fingerprint: {fingerprint}")
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _merge(self, path: Path, incoming: list[EndpointRecord]) -> list[EndpointRecord]:
        current: dict[str, EndpointRecord] = {}
        if path.exists():
            for item in json.loads(path.read_text(encoding="utf-8")):
                record = _record_from_dict(item)
                current[_fingerprint(record)] = record

        for record in incoming:
            key = _fingerprint(record)
            old = current.get(key)
            if old is None:
                current[key] = record
                continue
            old.evidence = sorted(set(old.evidence) | set(record.evidence))
            old.dynamic_fields = sorted(set(old.dynamic_fields) | set(record.dynamic_fields))
            old.sensitive_fields = sorted(set(old.sensitive_fields) | set(record.sensitive_fields))
            old.notes = sorted(set(old.notes) | set(record.notes))
            if record.demo_state == ValidationState.VERIFIED:
                old.demo_state = ValidationState.VERIFIED
            if record.live_state == ValidationState.VERIFIED:
                old.live_state = ValidationState.VERIFIED

        return sorted(
            current.values(),
            key=lambda item: (
                item.protocol_family,
                item.transport,
                item.endpoint_template,
                item.action,
            ),
        )


def _records_from_analysis(
    *,
    provider: str,
    analysis: AnalysisResult,
    evidence: EvidenceBundle,
    source_ref: str,
    environment: str,
) -> list[EndpointRecord]:
    by_id = {item.evidence_id: item for item in evidence.http}
    records: list[EndpointRecord] = []

    for contract in analysis.contracts:
        for transition in contract.transitions:
            sample = next((by_id[eid] for eid in transition.evidence_ids if eid in by_id), None)
            request = sample.request_body if sample is not None else None
            response = sample.response_body if sample is not None else None
            dynamic, sensitive = _field_classes(request)

            demo_state = ValidationState.OBSERVED
            live_state = ValidationState.UNKNOWN
            if environment == "live":
                live_state = ValidationState.OBSERVED

            records.append(
                EndpointRecord(
                    provider=provider,
                    protocol_family=contract.family,
                    action=transition.action or transition.name,
                    transport=transition.transport.value,
                    method=transition.method,
                    endpoint_template=_sanitize_url(transition.endpoint_template),
                    request_format=_template(request, request_side=True),
                    response_format=_template(response, request_side=False),
                    dynamic_fields=dynamic,
                    sensitive_fields=sensitive,
                    evidence=[source_ref, *transition.evidence_ids],
                    demo_state=demo_state,
                    live_state=live_state,
                    notes=list(transition.notes),
                )
            )
    return records


def _template(value: Any, *, request_side: bool, path: str = "$") -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            key_s = str(key)
            if _SENSITIVE_RE.search(key_s):
                out[key_s] = "<redacted>"
            elif request_side and _DYNAMIC_RE.search(key_s):
                out[key_s] = f"<dynamic:{key_s}>"
            else:
                out[key_s] = _template(child, request_side=request_side, path=f"{path}.{key_s}")
        return out
    if isinstance(value, list):
        return [_template(item, request_side=request_side, path=f"{path}[]") for item in value[:4]]
    if request_side:
        return value
    if value is None:
        return None
    if isinstance(value, bool):
        return "<bool>"
    if isinstance(value, (int, float)):
        return "<number>"
    if isinstance(value, str):
        return "<string>"
    return f"<{type(value).__name__}>"


def _field_classes(value: Any, *, path: str = "$") -> tuple[list[str], list[str]]:
    dynamic: list[str] = []
    sensitive: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if _SENSITIVE_RE.search(str(key)):
                sensitive.append(child_path)
            elif _DYNAMIC_RE.search(str(key)):
                dynamic.append(child_path)
            child_dynamic, child_sensitive = _field_classes(child, path=child_path)
            dynamic.extend(child_dynamic)
            sensitive.extend(child_sensitive)
    elif isinstance(value, list):
        for index, child in enumerate(value[:4]):
            child_dynamic, child_sensitive = _field_classes(child, path=f"{path}[{index}]")
            dynamic.extend(child_dynamic)
            sensitive.extend(child_sensitive)
    return sorted(set(dynamic)), sorted(set(sensitive))


def _sanitize_url(url: str) -> str:
    if "?" not in url:
        return url
    base, _ = url.split("?", 1)
    return base


def _fingerprint(record: EndpointRecord) -> str:
    raw = "|".join(
        [
            record.provider,
            record.protocol_family,
            record.action,
            record.transport,
            record.method or "",
            record.endpoint_template,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _record_from_dict(item: dict[str, Any]) -> EndpointRecord:
    return EndpointRecord(
        provider=item["provider"],
        protocol_family=item["protocol_family"],
        action=item["action"],
        transport=item["transport"],
        method=item.get("method"),
        endpoint_template=item["endpoint_template"],
        request_format=item.get("request_format"),
        response_format=item.get("response_format"),
        dynamic_fields=list(item.get("dynamic_fields") or []),
        sensitive_fields=list(item.get("sensitive_fields") or []),
        evidence=list(item.get("evidence") or []),
        demo_state=ValidationState(item.get("demo_state", ValidationState.UNKNOWN.value)),
        live_state=ValidationState(item.get("live_state", ValidationState.UNKNOWN.value)),
        notes=list(item.get("notes") or []),
    )


def _run_id(source_ref: str) -> str:
    digest = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:10]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{digest}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
