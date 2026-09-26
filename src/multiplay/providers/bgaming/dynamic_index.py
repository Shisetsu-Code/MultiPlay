from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

PROVEN = "PROVEN"
UNRESOLVED = "UNRESOLVED"
ACCEPTED = "ACCEPTED"
SEMANTIC_REJECTION = "SEMANTIC_REJECTION"
TRANSPORT_ERROR = "TRANSPORT_ERROR"
PROTOCOL_ERROR = "PROTOCOL_ERROR"


def prove_contiguous_index_domain(
    probes: Iterable[dict[str, Any]],
    *,
    min_boundary_confirmations: int = 2,
) -> dict[str, Any]:
    rows = [dict(row) for row in probes if isinstance(row, dict)]
    confirmations = _positive_int(min_boundary_confirmations, minimum=2, fallback=2)
    covered = _covered_indices(rows)
    unresolved = {
        "state": UNRESOLVED,
        "required_indices": [],
        "covered_indices": covered,
        "boundary_index": None,
        "boundary_confirmations": 0,
        "probes": rows,
    }
    if not rows:
        return unresolved

    by_index: dict[int, list[str]] = {}
    for row in rows:
        index = _probe_index(row)
        if index is None:
            return unresolved
        outcome = str(row.get("outcome") or "").strip().upper()
        if outcome not in {
            ACCEPTED,
            SEMANTIC_REJECTION,
            TRANSPORT_ERROR,
            PROTOCOL_ERROR,
        }:
            return unresolved
        by_index.setdefault(index, []).append(outcome)

    if any(len(set(outcomes)) != 1 for outcomes in by_index.values()):
        return unresolved

    rejected = sorted(
        index
        for index, outcomes in by_index.items()
        if outcomes and outcomes[0] == SEMANTIC_REJECTION
    )
    if len(rejected) != 1 or rejected[0] <= 0:
        return unresolved

    boundary = rejected[0]
    if sorted(by_index) != list(range(boundary + 1)):
        return unresolved
    if any(
        not by_index.get(index)
        or any(outcome != ACCEPTED for outcome in by_index[index])
        for index in range(boundary)
    ):
        return unresolved

    boundary_rows = by_index[boundary]
    if (
        len(boundary_rows) < confirmations
        or any(outcome != SEMANTIC_REJECTION for outcome in boundary_rows)
    ):
        return unresolved

    domain = list(range(boundary))
    return {
        "state": PROVEN,
        "required_indices": domain,
        "covered_indices": domain,
        "boundary_index": boundary,
        "boundary_confirmations": len(boundary_rows),
        "probes": rows,
    }


def probe_contiguous_index_domain(
    probe_index: Callable[[int], dict[str, Any]],
    *,
    max_index: int = 32,
    boundary_confirmations: int = 2,
) -> dict[str, Any]:
    guard = _positive_int(max_index, minimum=0, fallback=32)
    confirmations = _positive_int(boundary_confirmations, minimum=2, fallback=2)
    rows: list[dict[str, Any]] = []

    for index in range(guard + 1):
        row = _run_probe(probe_index, index)
        rows.append(row)
        outcome = row["outcome"]
        if outcome == ACCEPTED:
            continue
        if outcome == SEMANTIC_REJECTION:
            for _ in range(confirmations - 1):
                repeated = _run_probe(probe_index, index)
                rows.append(repeated)
                if repeated["outcome"] != SEMANTIC_REJECTION:
                    break
        break

    return prove_contiguous_index_domain(
        rows,
        min_boundary_confirmations=confirmations,
    )


def _run_probe(
    probe_index: Callable[[int], dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    try:
        raw = probe_index(index)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raw = {
            "index": index,
            "outcome": PROTOCOL_ERROR,
            "error": f"{type(exc).__name__}: {exc}",
        }
    row = dict(raw) if isinstance(raw, dict) else {}
    row["index"] = index
    outcome = str(row.get("outcome") or "").strip().upper()
    if not outcome:
        outcome = PROTOCOL_ERROR
    row["outcome"] = outcome
    return row


def _probe_index(row: dict[str, Any]) -> int | None:
    raw = row.get("index")
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _covered_indices(rows: list[dict[str, Any]]) -> list[int]:
    values: set[int] = set()
    for row in rows:
        index = _probe_index(row)
        if index is not None and str(row.get("outcome") or "").upper() == ACCEPTED:
            values.add(index)
    return sorted(values)


def _positive_int(value: Any, *, minimum: int, fallback: int) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return fallback
