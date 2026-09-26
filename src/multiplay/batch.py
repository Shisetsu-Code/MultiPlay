from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .endpoints import ProviderKnowledgeStore
from .evidence import HarError, load_har
from .pipeline import analyze_evidence


def analyze_har_directory(
    root: str | Path,
    *,
    provider: str | None,
    environment: str = "demo",
    knowledge_root: str | Path = "knowledge/providers",
    recursive: bool = True,
) -> dict[str, Any]:
    base = Path(root)
    if not base.is_dir():
        raise NotADirectoryError(str(base))
    if environment not in {"demo", "live"}:
        raise ValueError("environment must be demo or live")

    paths = sorted(
        base.rglob("*.har") if recursive else base.glob("*.har"),
        key=lambda path: str(path).casefold(),
    )
    rows: list[dict[str, Any]] = []
    statuses: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    runtime_families: Counter[str] = Counter()
    blockers: Counter[str] = Counter()

    store = ProviderKnowledgeStore(knowledge_root)

    for path in paths:
        relative = str(path.relative_to(base)).replace("\\", "/")
        source_ref = f"har:{relative}"
        try:
            evidence = load_har(path)
            result = analyze_evidence(evidence, provider=provider)
        except (HarError, json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
            error_type = type(exc).__name__
            errors[error_type] += 1
            rows.append(
                {
                    "path": relative,
                    "source_ref": source_ref,
                    "status": "ERROR",
                    "error_type": error_type,
                    "error": str(exc),
                }
            )
            continue

        payload = result.to_dict()
        statuses[result.analysis.status.value] += 1

        decision = result.provider_decision
        capture_families = sorted(
            {
                reason.removeprefix("runtime:")
                for reason in (decision.reasons if decision is not None else ())
                if reason.startswith("runtime:")
            }
        )
        for family in capture_families:
            runtime_families[family] += 1
        for blocker in result.provider_blockers or []:
            blockers[blocker] += 1
        row = {
            "path": relative,
            "source_ref": source_ref,
            "runtime_families": capture_families,
            **payload,
        }
        rows.append(row)

        if provider:
            records = (
                result.provider_adapter.endpoint_records(
                    evidence,
                    result.analysis,
                    source_ref=source_ref,
                    environment=environment,
                )
                if result.provider_adapter is not None
                else None
            )
            store.record_analysis(
                provider=provider,
                analysis=result.analysis,
                evidence=evidence,
                source_ref=source_ref,
                environment=environment,
                records=records,
            )

    return {
        "root": str(base),
        "provider": provider,
        "environment": environment,
        "recursive": recursive,
        "har_count": len(paths),
        "processed": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "runtime_family_counts": dict(sorted(runtime_families.items())),
        "blocker_counts": dict(
            sorted(blockers.items(), key=lambda item: (-item[1], item[0]))
        ),
        "error_counts": dict(sorted(errors.items())),
        "results": rows,
    }
