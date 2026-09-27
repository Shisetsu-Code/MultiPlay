from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ...action_graph import build_action_graph
from ...browser import BrowserAction, capture_browser_evidence
from ...endpoints import sanitize_endpoint_url
from ...evidence import load_har, redact
from ...models import EvidenceBundle, HttpExchange, ScriptEvidence
from .bootstrap import sanitize_session_url
from .classify import (
    API_V2,
    HYPERHIVE_JSONRPC,
    LEGACY_LINES,
    SWITCHABLE_CONTAINER,
    classify_bgaming,
)
from .demo_spin import run_demo_base_spin
from .direct_port import BGamingDemoDirectSession
from .handler_probe import probe_bgaming_handlers
from .hyperhive_demo import run_demo_hyperhive
from .probe import probe_bgaming_demo


def analyze_bgaming_demo(
    url: str,
    *,
    output_dir: str | Path,
    settle_ms: int = 10_000,
    timeout_s: float = 30.0,
    keep_raw_har: bool = False,
    screenshot: bool = True,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    raw_har = root / "browser.raw.har"
    shot = root / "initial.jpg" if screenshot else None
    capture_browser_evidence(
        url=url,
        har_path=raw_har,
        screenshot_path=shot,
        actions=[BrowserAction(kind="wait", timeout_ms=max(1000, int(settle_ms)))],
    )

    browser_evidence = load_har(raw_har)
    family = _detect_family(browser_evidence, url=url, timeout_s=timeout_s)

    blockers: list[str] = []
    hyperhive_base_error = ""
    enrichment: dict[str, Any] = {
        "attempted": False,
        "success": False,
        "kind": "",
    }
    extra = EvidenceBundle()

    if family in {API_V2, LEGACY_LINES}:
        enrichment["attempted"] = True
        enrichment["kind"] = "base-spin"
        try:
            base = run_demo_base_spin(url, timeout_s=timeout_s)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            blockers.append(f"base-spin enrichment failed: {type(exc).__name__}: {exc}")
        else:
            enrichment["success"] = 200 <= base.metadata.spin_status < 400
            enrichment["metadata"] = base.metadata.to_dict()
            extra = base.evidence
    elif family == HYPERHIVE_JSONRPC:
        enrichment["attempted"] = True
        enrichment["kind"] = "hyperhive-base-play"
        try:
            base = run_demo_hyperhive(url, timeout_s=timeout_s)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            hyperhive_base_error = (
                f"HyperHive base-play enrichment failed: "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            enrichment["success"] = 200 <= base.metadata.play_status < 400
            enrichment["metadata"] = base.metadata.to_dict()
            extra = base.evidence
    elif family == SWITCHABLE_CONTAINER:
        blockers.append(
            "switchable container requires child selection before direct base-play enrichment"
        )

    contract_bundle = _merge_evidence(browser_evidence, extra)
    contract_har = root / "contract.har"
    _write_safe_har(contract_bundle, contract_har)

    graph = build_action_graph(contract_har)
    routes = [dict(item) for item in graph.get("routes", [])]

    handler_probe: dict[str, Any] = {
        "attempted": False,
        "success": False,
        "route_id": "",
        "route_ids": [],
        "outcomes": [],
        "results": [],
    }
    handler_raw_hars: list[Path] = []

    candidates = _select_handler_probe_routes(routes)
    for index, candidate in enumerate(candidates, start=1):
        handler_probe["attempted"] = True
        route_id = str(candidate.get("route_id") or "")
        handler_probe["route_ids"].append(route_id)
        if not handler_probe["route_id"]:
            handler_probe["route_id"] = route_id

        handler_raw_har = root / f"handler-{index}.raw.har"
        handler_raw_hars.append(handler_raw_har)
        result_row: dict[str, Any] = {
            "route_id": route_id,
            "semantic": candidate.get("semantic"),
            "control": candidate.get("control"),
            "handler": candidate.get("handler"),
            "success": False,
            "outcomes": [],
        }

        try:
            probe = probe_bgaming_handlers(
                url,
                [candidate],
                har_path=handler_raw_har,
                settle_ms=max(8000, int(settle_ms)),
                after_call_ms=3500,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            result_row["error"] = f"{type(exc).__name__}: {exc}"
            handler_probe["results"].append(result_row)
            continue

        outcomes = [item.to_dict() for item in probe.outcomes]
        result_row["outcomes"] = outcomes
        handler_probe["outcomes"].extend(outcomes)
        matched = (
            any(item.called for item in probe.outcomes)
            and _probe_matches_route(probe.evidence, candidate)
        )
        result_row["success"] = matched
        result_row["request_count"] = len(probe.evidence.http)
        handler_probe["results"].append(result_row)

        if not matched:
            continue

        handler_probe["success"] = True
        contract_bundle = _merge_evidence(contract_bundle, probe.evidence)

    if handler_probe["success"]:
        _write_safe_har(contract_bundle, contract_har)
        graph = build_action_graph(contract_har)
        routes = [dict(item) for item in graph.get("routes", [])]
        if family == HYPERHIVE_JSONRPC and not enrichment["success"]:
            enrichment["success"] = True
            enrichment["kind"] = "handler-probe"
            enrichment["metadata"] = {
                "route_ids": [
                    row["route_id"]
                    for row in handler_probe["results"]
                    if row.get("success")
                ],
            }
            hyperhive_base_error = ""

    if hyperhive_base_error:
        blockers.append(hyperhive_base_error)
    if handler_probe.get("attempted") and not handler_probe.get("success"):
        blockers.append(
            "handler probe did not produce a matching successful request"
        )

    direct_state: dict[str, Any] | None = None
    direct_error = ""
    try:
        direct = BGamingDemoDirectSession(
            har_path=contract_har,
            url=url,
            timeout_s=timeout_s,
        )
        direct_state = direct.open()
        route_state = {item["route_id"]: item for item in direct.routes()}
        for route in routes:
            resolved = route_state.get(str(route.get("route_id") or ""))
            route["direct_executable"] = bool(
                resolved is not None and resolved.get("executable")
            )
            route["direct_reason"] = (
                str(resolved.get("execution_reason") or "")
                if resolved is not None
                else "route not present in direct session"
            )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        direct_error = f"{type(exc).__name__}: {exc}"
        for route in routes:
            route["direct_executable"] = False
            route["direct_reason"] = direct_error

    report = {
        "schema": "multiplay/bgaming-auto-analysis/v1",
        "url": _strip_query(url),
        "family": family,
        "enrichment": enrichment,
        "handler_probe": handler_probe,
        "blockers": blockers,
        "contract_har": str(contract_har),
        "screenshot": str(shot) if shot is not None else None,
        "route_count": len(routes),
        "direct_executable_count": sum(
            1 for item in routes if item.get("direct_executable")
        ),
        "routes": routes,
        "direct_session": direct_state,
        "direct_session_error": direct_error,
    }

    (root / "actions.json").write_text(
        json.dumps(
            {
                "schema": graph.get("schema"),
                "source": str(contract_har),
                "routes": routes,
                "endpoints": graph.get("endpoints", []),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if not keep_raw_har:
        raw_har.unlink(missing_ok=True)
        for handler_raw_har in handler_raw_hars:
            handler_raw_har.unlink(missing_ok=True)

    return report


def render_bgaming_analysis(report: dict[str, Any]) -> str:
    lines = [
        f"family: {report.get('family')}",
        f"routes: {report.get('route_count', 0)}",
        f"direct executable: {report.get('direct_executable_count', 0)}",
    ]

    enrichment = report.get("enrichment") or {}
    if enrichment.get("attempted"):
        lines.append(
            "base enrichment: "
            + ("OK" if enrichment.get("success") else "FAILED")
            + f" ({enrichment.get('kind')})"
        )

    for blocker in report.get("blockers") or []:
        lines.append(f"blocker: {blocker}")
    if report.get("direct_session_error"):
        lines.append(f"direct session: {report['direct_session_error']}")

    lines.extend(["", "ACTIONS"])
    for route in report.get("routes") or []:
        direct = "DIRECT" if route.get("direct_executable") else "-"
        lines.append(
            f"{route.get('route_id')}  "
            f"{route.get('semantic', ''):<12} "
            f"{route.get('interface_role', ''):<14} "
            f"{route.get('status', ''):<18} "
            f"{direct:<6} "
            f"{route.get('control', '')}"
        )
        handler = route.get("handler") or "-"
        chain = " -> ".join(route.get("chain") or []) or "-"
        wire = ", ".join(route.get("wire_markers") or []) or "-"
        lines.append(f"    handler: {handler}")
        lines.append(f"    chain:   {chain}")
        lines.append(f"    wire:    {wire}")
    return "\n".join(lines) + "\n"



def _select_handler_probe_routes(
    routes: list[dict[str, Any]],
    *,
    max_routes: int = 8,
) -> list[dict[str, Any]]:
    candidates = [
        route
        for route in routes
        if str(route.get("handler") or "").strip()
        and str(route.get("control") or "").strip()
        and route.get("interface_role") != "opener"
        and route.get("status") != "NETWORK_OBSERVED"
        and route.get("semantic")
        in {
            "SPIN",
            "BUY_BONUS",
            "FREESPIN",
            "RESPIN",
            "GAMBLE",
            "COLLECT",
            "PICK",
            "GAME_VARIANT",
            "CONTINUE",
        }
    ]

    priority = {
        "BUY_BONUS": 100,
        "SPIN": 90,
        "FREESPIN": 80,
        "RESPIN": 80,
        "PICK": 70,
        "GAMBLE": 60,
        "COLLECT": 60,
        "GAME_VARIANT": 50,
        "CONTINUE": 40,
    }

    def rank(route: dict[str, Any]) -> tuple[int, int, int, str]:
        markers = set(route.get("wire_markers") or [])
        score = priority.get(str(route.get("semantic") or ""), 0)
        if route.get("status") == "NETWORK_INFERRED":
            score += 20
        if any(
            str(marker).startswith("purchased_feature=")
            for marker in markers
        ):
            score += 30
        return (
            score,
            len(markers),
            len(str(route.get("handler") or "")),
            str(route.get("route_id") or ""),
        )

    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for route in candidates:
        key = (
            str(route.get("semantic") or ""),
            str(route.get("control") or ""),
            str(route.get("handler") or ""),
        )
        deduped.setdefault(key, route)

    return sorted(
        deduped.values(),
        key=rank,
        reverse=True,
    )[: max(1, int(max_routes))]


def _select_handler_probe_route(
    routes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Compatibility helper for callers/tests expecting one best route."""
    selected = _select_handler_probe_routes(routes, max_routes=1)
    return selected[0] if selected else None


def _probe_matches_route(
    evidence: EvidenceBundle,
    route: dict[str, Any],
) -> bool:
    wanted = set(route.get("wire_markers") or [])
    semantic = str(route.get("semantic") or "")
    handler = str(route.get("handler") or "")
    specific = {
        marker
        for marker in wanted
        if str(marker).startswith(
            (
                "purchased_feature=",
                "purchased_feature_level=",
                "action=",
                "bet_type=",
            )
        )
    }

    for exchange in evidence.http:
        if (
            exchange.response_status is None
            or not 200 <= exchange.response_status < 400
        ):
            continue

        observed = _request_markers(exchange.request_body)
        if specific and specific <= observed:
            return True

        if semantic == "SPIN" and (
            "command=spin" in observed
            or "method=play" in observed
        ):
            return True

        if semantic == "BUY_BONUS":
            purchased = [
                marker
                for marker in observed
                if str(marker).startswith("purchased_feature=")
            ]
            if purchased:
                if any(
                    marker.split("=", 1)[1] in handler
                    for marker in purchased
                ):
                    return True
                if "buy" in handler.casefold() or "bonus" in handler.casefold():
                    return True

            if (
                ("buy" in handler.casefold() or "bonus" in handler.casefold())
                and (
                    "command=spin" in observed
                    or "method=play" in observed
                )
            ):
                return True

        if wanted and wanted <= observed:
            return True
    return False


def _request_markers(value: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key)
            if name in {
                "command",
                "purchased_feature",
                "purchased_feature_level",
                "action",
                "method",
                "bet_type",
            } and isinstance(child, (str, int, float)) and not isinstance(child, bool):
                out.add(f"{name}={child}")
            out.update(_request_markers(child))
    elif isinstance(value, list):
        for child in value:
            out.update(_request_markers(child))
    return out

def _detect_family(
    evidence: EvidenceBundle,
    *,
    url: str,
    timeout_s: float,
) -> str:
    found = classify_bgaming(evidence)
    if found:
        return found[0].family

    probe = probe_bgaming_demo(url, timeout_s=timeout_s)
    found = classify_bgaming(probe.evidence)
    if found:
        return found[0].family
    raise ValueError("BGaming runtime family could not be classified.")


def _merge_evidence(
    primary: EvidenceBundle,
    secondary: EvidenceBundle,
) -> EvidenceBundle:
    http: list[HttpExchange] = []
    seen_http: set[str] = set()
    for item in [*primary.http, *secondary.http]:
        key = json.dumps(
            {
                "method": item.method,
                "url": _safe_contract_url(item.url),
                "request": item.request_body,
                "status": item.response_status,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if key in seen_http:
            continue
        seen_http.add(key)
        http.append(item)

    scripts: list[ScriptEvidence] = []
    seen_scripts: set[str] = set()
    for item in [*primary.scripts, *secondary.scripts]:
        key = f"{_strip_query(item.source)}\n{item.text}"
        if key in seen_scripts:
            continue
        seen_scripts.add(key)
        scripts.append(item)

    return EvidenceBundle(
        http=http,
        websocket=[*primary.websocket, *secondary.websocket],
        scripts=scripts,
        ui=[*primary.ui, *secondary.ui],
        metadata={
            "source": "bgaming-auto-analysis",
            "merged_sources": [
                primary.metadata.get("source"),
                secondary.metadata.get("source"),
            ],
        },
    )


def _write_safe_har(bundle: EvidenceBundle, path: Path) -> None:
    entries: list[dict[str, Any]] = []

    for exchange in bundle.http:
        if not _keep_contract_exchange(exchange):
            continue
        entries.append(
            {
                "request": {
                    "method": exchange.method,
                    "url": _safe_contract_url(exchange.url),
                    "headers": [
                        {"name": key, "value": value}
                        for key, value in redact(exchange.request_headers).items()
                    ],
                    "postData": (
                        {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                redact(exchange.request_body),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        }
                        if exchange.request_body is not None
                        else None
                    ),
                },
                "response": {
                    "status": exchange.response_status or 0,
                    "headers": [
                        {"name": key, "value": value}
                        for key, value in redact(exchange.response_headers).items()
                    ],
                    "content": {
                        "mimeType": "application/json",
                        "text": json.dumps(
                            redact(exchange.response_body),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                },
            }
        )

    for script in bundle.scripts:
        entries.append(
            {
                "request": {
                    "method": "GET",
                    "url": _strip_query(script.source),
                    "headers": [],
                },
                "response": {
                    "status": 200,
                    "headers": [],
                    "content": {
                        "mimeType": "application/javascript",
                        "text": script.text,
                    },
                },
            }
        )

    path.write_text(
        json.dumps(
            {
                "log": {
                    "version": "1.2",
                    "creator": {"name": "MultiPlay", "version": "0.1"},
                    "entries": entries,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _strip_query(url: str) -> str:
    parts = urlsplit(str(url or ""))
    return parts._replace(query="", fragment="").geturl()



def _safe_contract_url(url: str) -> str:
    return sanitize_session_url(sanitize_endpoint_url(str(url or "")))



def _keep_contract_exchange(exchange: HttpExchange) -> bool:
    parts = urlsplit(str(exchange.url or ""))
    host = (parts.hostname or "").casefold()
    if not (
        host == "bgaming-network.com"
        or host.endswith(".bgaming-network.com")
    ):
        return False

    method = str(exchange.method or "").upper()
    if method not in {"GET", "HEAD", "OPTIONS"}:
        return True

    path = parts.path.casefold()
    return (
        "/api/" in path
        or path.endswith("/api")
        or "/lobby/" in path
        or "/launch" in path
        or path.rstrip("/").endswith("/hyperhive")
        or "/games/" in path
    )
