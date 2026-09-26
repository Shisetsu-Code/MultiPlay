from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...endpoints import ProviderKnowledgeStore
from ...pipeline import analyze_evidence
from .probe import ProbeResult, probe_bgaming_demo

ProbeFn = Callable[..., ProbeResult]


def sweep_catalog_file(
    path: str | Path,
    *,
    limit: int = 0,
    delay_s: float = 0.25,
    timeout_s: float = 30.0,
    knowledge_root: str | Path = "knowledge/providers",
    probe_fn: ProbeFn = probe_bgaming_demo,
) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return sweep_catalog_payload(
        payload,
        limit=limit,
        delay_s=delay_s,
        timeout_s=timeout_s,
        knowledge_root=knowledge_root,
        probe_fn=probe_fn,
    )


def sweep_catalog_payload(
    payload: Any,
    *,
    limit: int = 0,
    delay_s: float = 0.25,
    timeout_s: float = 30.0,
    knowledge_root: str | Path = "knowledge/providers",
    probe_fn: ProbeFn = probe_bgaming_demo,
) -> dict[str, Any]:
    records = _catalog_records(payload)
    cap = max(0, int(limit))
    if cap:
        records = records[:cap]

    delay = max(0.0, float(delay_s))
    timeout = max(1.0, float(timeout_s))
    store = ProviderKnowledgeStore(knowledge_root)

    rows: list[dict[str, Any]] = []
    families: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    availability: Counter[str] = Counter()

    for index, record in enumerate(records):
        slug = str(record.get("slug") or "").strip()
        name = str(record.get("name") or slug).strip()
        target = str(
            record.get("execution_url")
            or record.get("demo_url")
            or record.get("public_url")
            or ""
        ).strip()
        availability_name = str(record.get("availability") or "UNKNOWN")
        availability[availability_name] += 1

        print(f"[{index + 1}/{len(records)}] BGaming probe {slug or name}", flush=True)
        row: dict[str, Any] = {
            "slug": slug,
            "name": name,
            "availability": availability_name,
            "target_kind": _target_kind(record),
        }
        if not target:
            row.update(
                {
                    "status": "ERROR",
                    "error_type": "MissingTarget",
                    "error": "catalog record has no execution/public URL",
                    "runtime_families": [],
                }
            )
            rows.append(row)
            failures["MissingTarget"] += 1
            print("  -> ERROR MissingTarget", flush=True)
            continue

        try:
            probe = probe_fn(target, timeout_s=timeout)
            result = analyze_evidence(probe.evidence, provider="bgaming")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            error_type = type(exc).__name__
            failures[error_type] += 1
            row.update(
                {
                    "status": "ERROR",
                    "error_type": error_type,
                    "error": str(exc),
                    "runtime_families": [],
                }
            )
            rows.append(row)
            print(f"  -> ERROR {error_type}: {exc}", flush=True)
        else:
            runtime_families = _runtime_families(result.provider_decision)
            for family in runtime_families:
                families[family] += 1
            status = result.analysis.status.value
            statuses[status] += 1

            probe_meta = probe.metadata.to_dict()
            row.update(
                {
                    "status": status,
                    "runtime_families": runtime_families,
                    "probe": probe_meta,
                    "provider_blockers": list(result.provider_blockers or []),
                    "analysis_reasons": list(result.analysis.reasons),
                }
            )
            rows.append(row)
            family_label = ",".join(runtime_families) if runtime_families else "unclassified"
            print(f"  -> {status} [{family_label}]", flush=True)

            source_ref = f"probe:bgaming:{slug or index}"
            endpoint_records = (
                result.provider_adapter.endpoint_records(
                    probe.evidence,
                    result.analysis,
                    source_ref=source_ref,
                    environment="demo",
                )
                if result.provider_adapter is not None
                else None
            )
            store.record_analysis(
                provider="bgaming",
                analysis=result.analysis,
                evidence=probe.evidence,
                source_ref=source_ref,
                environment="demo",
                records=endpoint_records,
            )

        if delay and index + 1 < len(records):
            time.sleep(delay)

    classified = sum(families.values())
    return {
        "provider": "bgaming",
        "catalog_authoritative": bool(
            payload.get("authoritative")
            if isinstance(payload, dict)
            else False
        ),
        "catalog_records": len(_catalog_records(payload)),
        "attempted": len(records),
        "classified_family_observations": classified,
        "runtime_family_counts": dict(sorted(families.items())),
        "status_counts": dict(sorted(statuses.items())),
        "failure_counts": dict(sorted(failures.items())),
        "availability_counts": dict(sorted(availability.items())),
        "results": rows,
    }


def _catalog_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw = payload.get("records")
    elif isinstance(payload, list):
        raw = payload
    else:
        raise TypeError("BGaming catalog payload must be an object or list.")

    if not isinstance(raw, list):
        raise TypeError("BGaming catalog does not contain a records list.")
    return [dict(item) for item in raw if isinstance(item, dict)]


def _runtime_families(decision: Any) -> list[str]:
    reasons = getattr(decision, "reasons", ()) if decision is not None else ()
    return sorted(
        {
            str(reason).removeprefix("runtime:")
            for reason in reasons
            if str(reason).startswith("runtime:")
        }
    )


def _target_kind(record: dict[str, Any]) -> str:
    if record.get("demo_url"):
        return "DEMO"
    if record.get("execution_url") and record.get("execution_url") != record.get("public_url"):
        return "EXECUTION"
    return "PUBLIC_RESOLVE"
