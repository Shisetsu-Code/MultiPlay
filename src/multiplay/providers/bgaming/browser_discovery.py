from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ...browser import explore_browser
from ...endpoints import ProviderKnowledgeStore
from ...evidence import load_har
from ...pipeline import analyze_evidence
from .probe import probe_bgaming_demo


def discover_family_with_browser(
    *,
    catalog_path: str | Path,
    family: str,
    output_dir: str | Path,
    max_probes: int = 80,
    probe_delay_s: float = 1.0,
    timeout_s: float = 30.0,
    max_clicks: int = 28,
    settle_ms: int = 4000,
    headless: bool = True,
    knowledge_root: str | Path = "knowledge/providers",
    keep_har: bool = False,
    family_map_path: str | Path = "knowledge/providers/bgaming/family-map.json",
) -> dict[str, Any]:
    """Pick a current runtime representative, then discover actions through Playwright.

    The provider layer selects only by current runtime family. It contains no game title,
    button text, selector, endpoint, payload, or click coordinate.
    """
    payload = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    records = _catalog_records(payload)
    wanted = str(family or "").strip()
    if not wanted:
        raise ValueError("BGaming family is required.")

    records = _prioritize_family_cache(
        records,
        family=wanted,
        family_map_path=family_map_path,
    )

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    launch_url = ""
    selection_path = root / "selection.json"

    for index, record in enumerate(records[: max(1, int(max_probes))], start=1):
        target = str(
            record.get("execution_url")
            or record.get("demo_url")
            or record.get("public_url")
            or ""
        ).strip()
        if not target:
            continue

        slug = str(record.get("slug") or "").strip()
        try:
            probe = probe_bgaming_demo(target, timeout_s=timeout_s)
            analysis = analyze_evidence(probe.evidence, provider="bgaming")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            attempts.append(
                {
                    "index": index,
                    "slug": slug,
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            _write_selection(selection_path, selected, attempts)
        else:
            families = _families(analysis.provider_decision)
            attempts.append(
                {
                    "index": index,
                    "slug": slug,
                    "status": analysis.analysis.status.value,
                    "runtime_families": families,
                }
            )
            _write_selection(selection_path, selected, attempts)
            if wanted in families:
                selected = {
                    "slug": slug,
                    "name": str(record.get("name") or slug),
                    "family": wanted,
                    "probe": probe.metadata.to_dict(),
                }
                launch_url = probe.metadata.launch_url
                _write_selection(selection_path, selected, attempts)
                break

        if probe_delay_s > 0:
            time.sleep(float(probe_delay_s))

    if selected is None or not launch_url:
        raise RuntimeError(
            f"BGaming browser discovery found no current {wanted!r} representative "
            f"in {min(len(records), max(1, int(max_probes)))} probes."
        )

    _write_selection(selection_path, selected, attempts)

    browser = explore_browser(
        url=launch_url,
        output_dir=root,
        max_clicks=max_clicks,
        settle_ms=settle_ms,
        headless=headless,
    )

    evidence = load_har(browser.har_path)
    analysis = analyze_evidence(evidence, provider="bgaming")
    source_ref = f"browser:bgaming:{wanted}:{selected['slug']}"
    endpoint_records = (
        analysis.provider_adapter.endpoint_records(
            evidence,
            analysis.analysis,
            source_ref=source_ref,
            environment="demo",
        )
        if analysis.provider_adapter is not None
        else None
    )
    ProviderKnowledgeStore(knowledge_root).record_analysis(
        provider="bgaming",
        analysis=analysis.analysis,
        evidence=evidence,
        source_ref=source_ref,
        environment="demo",
        records=endpoint_records,
    )

    (root / "analysis.json").write_text(
        json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if not keep_har:
        browser.har_path.unlink(missing_ok=True)

    result = {
        "selected": selected,
        "browser": browser.to_dict(),
        "analysis": analysis.to_dict(),
    }
    if not keep_har:
        result["browser"]["har_path"] = None
    return result




def _write_selection(
    path: Path,
    selected: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
) -> None:
    path.write_text(
        json.dumps(
            {
                "selected": selected,
                "attempts": attempts,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )



def _prioritize_family_cache(
    records: list[dict[str, Any]],
    *,
    family: str,
    family_map_path: str | Path,
) -> list[dict[str, Any]]:
    path = Path(family_map_path)
    if not path.is_file():
        return records

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return records
    if not isinstance(payload, dict):
        return records
    if payload.get("schema") != "multiplay/bgaming-family-map/v1":
        return records
    if str(payload.get("catalog_slugs_sha256") or "") != _catalog_slug_hash(records):
        return records

    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return records

    preferred = []
    fallback = []
    for record in records:
        slug = str(record.get("slug") or "")
        families = entries.get(slug)
        if isinstance(families, list) and family in {str(item) for item in families}:
            preferred.append(record)
        else:
            fallback.append(record)
    return [*preferred, *fallback]


def _catalog_slug_hash(records: list[dict[str, Any]]) -> str:
    slugs = sorted(
        str(record.get("slug") or "")
        for record in records
        if str(record.get("slug") or "")
    )
    return hashlib.sha256("\n".join(slugs).encode("utf-8")).hexdigest()


def _catalog_records(payload: Any) -> list[dict[str, Any]]:
    raw = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise TypeError("BGaming catalog does not contain records.")
    return [dict(item) for item in raw if isinstance(item, dict)]


def _families(decision: Any) -> list[str]:
    reasons = getattr(decision, "reasons", ()) if decision is not None else ()
    return sorted(
        {
            str(reason).removeprefix("runtime:")
            for reason in reasons
            if str(reason).startswith("runtime:")
        }
    )
