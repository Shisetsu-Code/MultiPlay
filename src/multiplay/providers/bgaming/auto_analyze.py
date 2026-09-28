from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ...action_graph import build_action_graph
from ...browser import BrowserAction, capture_browser_evidence
from ...endpoints import sanitize_endpoint_url
from ...evidence import load_har, redact
from ...models import EvidenceBundle, HttpExchange, ScriptEvidence
from .bootstrap import sanitize_session_url
from .catalog import resolve_catalog_execution_url
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
from .hyperhive_static import (
    HyperHiveStaticProfile,
    discover_hyperhive_static_profile,
)
from .probe import _identity_key, _public_game_slug, probe_bgaming_demo
from .switchable import (
    extract_switchable_variants,
    route_child_index,
    switchable_child_url,
)


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

    requested_url = str(url or "").strip()
    execution_url = requested_url
    source_host = (urlsplit(requested_url).hostname or "").casefold()
    if source_host == "bgaming.com" or source_host.endswith(".bgaming.com"):
        execution_url = resolve_catalog_execution_url(
            requested_url,
            timeout_s=timeout_s,
        )

    if source_host == "bgaming.com" or source_host.endswith(".bgaming.com"):
        resolved_host = (urlsplit(execution_url).hostname or "").casefold()
        if resolved_host == "bgaming.com" or resolved_host.endswith(".bgaming.com"):
            try:
                public_probe = probe_bgaming_demo(
                    requested_url,
                    timeout_s=timeout_s,
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                return _write_unresolved_runtime_report(
                    root,
                    requested_url=requested_url,
                    reason=(
                        "no matching BGaming demo runtime could be resolved: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            execution_url = public_probe.metadata.launch_url

    raw_har = root / "browser.raw.har"
    shot = root / "initial.jpg" if screenshot else None
    capture_browser_evidence(
        url=execution_url,
        har_path=raw_har,
        screenshot_path=shot,
        actions=[BrowserAction(kind="wait", timeout_ms=max(1000, int(settle_ms)))],
    )

    browser_evidence = load_har(raw_har)
    _require_runtime_identity(url, browser_evidence)
    family = _detect_family(browser_evidence, url=execution_url, timeout_s=timeout_s)
    static_profile = (
        discover_hyperhive_static_profile(browser_evidence)
        if family == HYPERHIVE_JSONRPC
        else None
    )

    blockers: list[str] = []
    hyperhive_base_error = ""
    enrichment: dict[str, Any] = {
        "attempted": False,
        "success": False,
        "kind": "",
    }
    extra = EvidenceBundle()
    switchable_variants: list[str] = []
    switchable_children: list[dict[str, Any]] = []

    if family in {API_V2, LEGACY_LINES}:
        enrichment["attempted"] = True
        enrichment["kind"] = "base-spin"
        try:
            base = run_demo_base_spin(
                execution_url,
                timeout_s=timeout_s,
                client_scripts=[
                    item.text
                    for item in browser_evidence.scripts
                    if str(item.text or "").strip()
                ],
            )
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
            base = run_demo_hyperhive(execution_url, timeout_s=timeout_s)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            hyperhive_base_error = (
                f"HyperHive base-play enrichment failed: "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            enrichment["success"] = bool(base.metadata.play_success)
            enrichment["metadata"] = base.metadata.to_dict()
            extra = base.evidence
    elif family == SWITCHABLE_CONTAINER:
        enrichment["attempted"] = True
        enrichment["kind"] = "switchable-children"
        try:
            parent_probe = probe_bgaming_demo(
                execution_url,
                timeout_s=timeout_s,
            )
            parent_identifier = parent_probe.metadata.identifier
            parent_evidence = _merge_evidence(
                browser_evidence,
                parent_probe.evidence,
            )
            switchable_variants = extract_switchable_variants(
                parent_evidence,
                parent_identifier,
            )
            if not switchable_variants:
                raise ValueError(
                    "switchable runtime exposed no child identifier table"
                )

            for child_identifier in switchable_variants:
                child_url = switchable_child_url(
                    execution_url,
                    child_identifier,
                )
                row: dict[str, Any] = {
                    "identifier": child_identifier,
                    "url": _strip_query(child_url),
                    "success": False,
                }
                try:
                    child = run_demo_base_spin(
                        child_url,
                        timeout_s=timeout_s,
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    row["error"] = f"{type(exc).__name__}: {exc}"
                else:
                    row["family"] = child.metadata.family
                    row["init_status"] = child.metadata.init_status
                    row["spin_status"] = child.metadata.spin_status
                    row["success"] = (
                        200 <= child.metadata.init_status < 400
                        and 200 <= child.metadata.spin_status < 400
                    )
                switchable_children.append(row)

            enrichment["success"] = bool(switchable_children) and all(
                bool(item.get("success"))
                for item in switchable_children
            )
            enrichment["metadata"] = {
                "parent_identifier": parent_identifier,
                "children": switchable_children,
            }
            extra = parent_probe.evidence
            if not enrichment["success"]:
                blockers.append(
                    "one or more switchable child base spins failed"
                )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            blockers.append(
                "switchable child enrichment failed: "
                f"{type(exc).__name__}: {exc}"
            )

    contract_bundle = _merge_evidence(browser_evidence, extra)
    contract_har = root / "contract.har"
    _write_safe_har(contract_bundle, contract_har)

    graph = build_action_graph(contract_har)
    routes = [dict(item) for item in graph.get("routes", [])]
    if family == HYPERHIVE_JSONRPC:
        _seed_hyperhive_spin_routes(routes)
        _seed_hyperhive_static_routes(routes, static_profile)
    elif family == API_V2:
        _seed_api_v2_buy_feature_routes(routes, browser_evidence)

    if switchable_variants:
        by_identifier = {
            str(item.get("identifier") or ""): item
            for item in switchable_children
        }
        for route in routes:
            index = route_child_index(route)
            if index is None or index >= len(switchable_variants):
                continue
            identifier = switchable_variants[index]
            child = by_identifier.get(identifier) or {}
            route["child_identifier"] = identifier
            route["child_spin_validated"] = bool(child.get("success"))

    handler_probe: dict[str, Any] = {
        "attempted": False,
        "success": False,
        "route_id": "",
        "route_ids": [],
        "outcomes": [],
        "results": [],
    }
    handler_raw_hars: list[Path] = []

    candidates = (
        []
        if family == SWITCHABLE_CONTAINER
        else _select_handler_probe_routes(routes)
    )
    if family == API_V2 and not enrichment.get("success"):
        fallback_spin = _select_base_spin_browser_fallback(routes)
        if fallback_spin is not None:
            fallback_id = str(fallback_spin.get("route_id") or "")
            candidates = [
                fallback_spin,
                *[
                    item
                    for item in candidates
                    if str(item.get("route_id") or "") != fallback_id
                ],
            ]

    browser_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if "static_request_fields" in candidate:
            continue
        markers = {
            str(item)
            for item in candidate.get("wire_markers") or []
        }
        direct_api_purchase = (
            family == API_V2
            and candidate.get("semantic") == "BUY_BONUS"
            and any(
                marker.startswith("purchased_feature=")
                for marker in markers
            )
        )
        direct_hyper_play = (
            family == HYPERHIVE_JSONRPC
            and enrichment.get("success")
            and "method=play" in markers
        )
        if direct_api_purchase or direct_hyper_play:
            continue
        browser_candidates.append(candidate)
        if len(browser_candidates) >= 4:
            break

    for index, candidate in enumerate(browser_candidates, start=1):
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
                execution_url,
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

    # If the synthetic base spin failed but an explicit client spin handler
    # produced a valid request, persist it before inferred purchases. This lets
    # the direct session learn the provider's real successful payload shape.
    if handler_probe["success"]:
        _write_safe_har(contract_bundle, contract_har)

    if family == API_V2:
        succeeded = {
            str(row.get("route_id") or "")
            for row in handler_probe["results"]
            if row.get("success")
        }
        for index, candidate in enumerate(candidates, start=1):
            route_id = str(candidate.get("route_id") or "")
            markers = tuple(
                str(item)
                for item in candidate.get("wire_markers") or []
            )
            has_feature = any(
                marker.startswith("purchased_feature=")
                for marker in markers
            )
            if (
                route_id in succeeded
                or candidate.get("semantic") != "BUY_BONUS"
                or not has_feature
            ):
                continue

            row: dict[str, Any] = {
                "route_id": route_id,
                "semantic": candidate.get("semantic"),
                "control": candidate.get("control"),
                "handler": candidate.get("handler"),
                "kind": "direct-inferred-api-v2-purchase",
                "success": False,
                "outcomes": [],
            }
            try:
                direct_probe = BGamingDemoDirectSession(
                    har_path=contract_har,
                    url=execution_url,
                    timeout_s=timeout_s,
                )
                direct_probe.open()
                direct_result = direct_probe.execute_inferred_api_v2_purchase(markers)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                handler_probe["results"].append(row)
                continue

            row["status"] = direct_result.get("status")
            row["request"] = direct_result.get("request")
            row["response"] = direct_result.get("response")
            row["success"] = bool(direct_result.get("success"))
            if not row["success"]:
                handler_probe["results"].append(row)
                continue

            inferred = EvidenceBundle(
                http=[
                    HttpExchange(
                        evidence_id=f"api-v2:inferred:{index}",
                        method="POST",
                        url=str(direct_result.get("endpoint") or ""),
                        request_body=direct_result.get("request"),
                        response_status=int(direct_result.get("status") or 0),
                        response_body=direct_result.get("response"),
                    )
                ],
                metadata={"source": "bgaming-api-v2-direct-inferred"},
            )
            matched = _probe_matches_route(inferred, candidate)
            row["success"] = matched
            handler_probe["results"].append(row)
            if not matched:
                continue

            handler_probe["success"] = True
            succeeded.add(route_id)
            contract_bundle = _merge_evidence(contract_bundle, inferred)

    if family == HYPERHIVE_JSONRPC:
        succeeded = {
            str(row.get("route_id") or "")
            for row in handler_probe["results"]
            if row.get("success")
        }
        for index, candidate in enumerate(candidates, start=1):
            route_id = str(candidate.get("route_id") or "")
            markers = tuple(
                str(item)
                for item in candidate.get("wire_markers") or []
            )
            if route_id in succeeded or "method=play" not in markers:
                continue
            if (
                candidate.get("semantic") == "BUY_BONUS"
                and not any(
                    marker.startswith("purchased_feature=")
                    for marker in markers
                )
            ):
                continue

            row: dict[str, Any] = {
                "route_id": route_id,
                "semantic": candidate.get("semantic"),
                "control": candidate.get("control"),
                "handler": candidate.get("handler"),
                "kind": "direct-inferred-hyperhive",
                "success": False,
                "outcomes": [],
            }
            try:
                direct_probe = BGamingDemoDirectSession(
                    har_path=contract_har,
                    url=execution_url,
                    timeout_s=timeout_s,
                )
                direct_probe.open()
                if "static_request_fields" in candidate:
                    direct_result = direct_probe.execute_inferred_hyperhive_fields(
                        dict(candidate.get("static_request_fields") or {}),
                        state_lock_required=bool(
                            candidate.get("static_state_lock_required")
                        ),
                    )
                else:
                    direct_result = direct_probe.execute_inferred_hyperhive(markers)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                handler_probe["results"].append(row)
                continue

            row["status"] = direct_result.get("status")
            row["request"] = direct_result.get("request")
            row["response"] = direct_result.get("response")
            row["success"] = bool(direct_result.get("success"))
            if not row["success"]:
                handler_probe["results"].append(row)
                continue

            inferred = EvidenceBundle(
                http=[
                    HttpExchange(
                        evidence_id=f"hyperhive:inferred:{index}",
                        method="POST",
                        url=str(direct_result.get("endpoint") or ""),
                        request_body=direct_result.get("request"),
                        response_status=int(direct_result.get("status") or 0),
                        response_body=direct_result.get("response"),
                    )
                ],
                metadata={"source": "bgaming-hyperhive-direct-inferred"},
            )
            matched = _probe_matches_route(inferred, candidate)
            row["success"] = matched
            handler_probe["results"].append(row)
            if not matched:
                continue

            handler_probe["success"] = True
            succeeded.add(route_id)
            contract_bundle = _merge_evidence(contract_bundle, inferred)

    if handler_probe["success"]:
        _write_safe_har(contract_bundle, contract_har)
        graph = build_action_graph(contract_har)
        routes = [dict(item) for item in graph.get("routes", [])]
        if family == HYPERHIVE_JSONRPC:
            _seed_hyperhive_spin_routes(routes)
        elif family == API_V2:
            _seed_api_v2_buy_feature_routes(routes, contract_bundle)
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
    if (
        handler_probe.get("attempted")
        and not handler_probe.get("success")
        and not enrichment.get("success")
    ):
        blockers.append(
            "handler probe did not produce a matching successful request"
        )

    direct_state: dict[str, Any] | None = None
    direct_error = ""
    if family == SWITCHABLE_CONTAINER:
        direct_state = {
            "provider": "bgaming",
            "environment": "demo",
            "family": family,
            "children": switchable_children,
        }
        for route in routes:
            route["direct_executable"] = False
            route["direct_reason"] = (
                "switchable route requires a validated child selection"
            )
    else:
        try:
            direct = BGamingDemoDirectSession(
                har_path=contract_har,
                url=execution_url,
                timeout_s=timeout_s,
            )
            direct_state = direct.open()
            route_state = {item["route_id"]: item for item in direct.routes()}
            for route in routes:
                if "static_request_fields" in route:
                    observed = _probe_matches_route(contract_bundle, route)
                    route["direct_executable"] = observed
                    route["direct_reason"] = (
                        ""
                        if observed
                        else "static HyperHive wire was not accepted by the provider"
                    )
                    continue
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
        "url": _strip_query(requested_url),
        "execution_url": _strip_query(execution_url),
        "family": family,
        "static_profile": (
            static_profile.to_dict()
            if static_profile is not None
            else None
        ),
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
        "switchable_children": switchable_children,
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


def _write_unresolved_runtime_report(
    root: Path,
    *,
    requested_url: str,
    reason: str,
) -> dict[str, Any]:
    contract_har = root / "contract.har"
    _write_safe_har(
        EvidenceBundle(
            metadata={"source": "bgaming-auto-analysis-unresolved"}
        ),
        contract_har,
    )
    actions = {
        "schema": "multiplay/action-graph/v1",
        "source": str(contract_har),
        "routes": [],
        "endpoints": [],
    }
    (root / "actions.json").write_text(
        json.dumps(actions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = {
        "schema": "multiplay/bgaming-auto-analysis/v1",
        "status": "PARTIAL_REQUIRES_REVIEW",
        "runtime_status": "NO_RESOLVABLE_DEMO",
        "url": _strip_query(requested_url),
        "execution_url": "",
        "family": "unresolved",
        "enrichment": {
            "attempted": False,
            "success": False,
            "kind": "",
        },
        "handler_probe": {
            "attempted": False,
            "success": False,
            "route_id": "",
            "route_ids": [],
            "outcomes": [],
            "results": [],
        },
        "blockers": [reason],
        "contract_har": str(contract_har),
        "screenshot": None,
        "route_count": 0,
        "direct_executable_count": 0,
        "routes": [],
        "direct_session": None,
        "direct_session_error": reason,
    }
    (root / "analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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

    children = report.get("switchable_children") or []
    if children:
        lines.extend(["", "SWITCHABLE CHILDREN"])
        for child in children:
            state = "DIRECT-SPIN" if child.get("success") else "FAILED"
            lines.append(
                f"{state:<11} "
                f"{child.get('identifier', '')} "
                f"init={child.get('init_status', '-')} "
                f"spin={child.get('spin_status', '-')}"
            )

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
        if route.get("child_identifier"):
            lines.append(
                "    child:   "
                f"{route.get('child_identifier')} "
                f"validated={bool(route.get('child_spin_validated'))}"
            )
    return "\n".join(lines) + "\n"



def _seed_hyperhive_static_routes(
    routes: list[dict[str, Any]],
    profile: HyperHiveStaticProfile | None,
) -> None:
    if profile is None:
        return

    existing_ids = {
        str(route.get("route_id") or "")
        for route in routes
    }

    if profile.base_wire_complete:
        has_observed_spin = any(
            route.get("semantic") == "SPIN"
            and route.get("status") == "NETWORK_OBSERVED"
            for route in routes
        )
        route_id = "static-hyperhive:spin"
        if not has_observed_spin and route_id not in existing_ids:
            fields = dict(profile.base_request_fields or {})
            routes.append(
                {
                    "route_id": route_id,
                    "semantic": "SPIN",
                    "status": "NETWORK_INFERRED",
                    "interface_role": "network_action",
                    "control": "protocol:static-spin",
                    "handler": f"static:{profile.source}",
                    "wire_markers": _static_wire_markers(fields),
                    "confidence": "HIGH",
                    "static_request_fields": fields,
                    "static_state_lock_required": profile.state_lock_required,
                    "static_wire_complete": True,
                }
            )
            existing_ids.add(route_id)

    for mode in profile.modes:
        route_id = f"static-hyperhive:{mode.mode_id}"
        if route_id in existing_ids:
            continue
        fields = (
            dict(mode.request_fields)
            if isinstance(mode.request_fields, dict)
            else None
        )
        routes.append(
            {
                "route_id": route_id,
                "semantic": "BUY_BONUS",
                "status": (
                    "NETWORK_INFERRED"
                    if mode.wire_complete
                    else "CLIENT_STATIC_DECLARED"
                ),
                "interface_role": "network_action",
                "control": f"protocol:{mode.mode_id}",
                "handler": f"static:{mode.source}",
                "wire_markers": (
                    _static_wire_markers(fields)
                    if fields is not None
                    else ["method=play"]
                ),
                "confidence": "HIGH",
                "static_request_fields": fields,
                "static_state_lock_required": profile.state_lock_required,
                "static_wire_complete": mode.wire_complete,
                "declared_multiplier": mode.multiplier,
                "wire_requirements": list(mode.requirements),
            }
        )
        existing_ids.add(route_id)


def _static_wire_markers(
    fields: dict[str, Any] | None,
) -> list[str]:
    markers = {"method=play"}
    if fields is None:
        return sorted(markers)

    for key, value in fields.items():
        if isinstance(value, str) and value.startswith("$"):
            continue
        if value is True:
            marker_value = "true"
        elif value is False:
            marker_value = "false"
        elif value is None:
            marker_value = "null"
        elif isinstance(value, (str, int, float)):
            marker_value = str(value)
        else:
            continue
        markers.add(f"{key}={marker_value}")
    return sorted(markers)


def _seed_api_v2_buy_feature_routes(
    routes: list[dict[str, Any]],
    evidence: EvidenceBundle,
) -> None:
    """Link generic BuyFeaturePopupItem controls to client-declared feature rows."""
    features = _api_v2_static_buy_features(evidence)
    if not features:
        return

    for route in routes:
        if route.get("semantic") != "BUY_BONUS":
            continue
        markers = {str(item) for item in route.get("wire_markers") or []}
        if any(item.startswith("purchased_feature=") for item in markers):
            continue

        control_key = _feature_key(str(route.get("control") or ""))
        if not control_key:
            continue

        matches = [
            row
            for row in features
            if control_key.endswith(_feature_key(str(row.get("name") or "")))
            and str(row.get("request_name") or "").strip()
        ]
        signatures = {
            (
                str(row.get("request_name") or ""),
                str(row.get("level") or ""),
            )
            for row in matches
        }
        if len(signatures) != 1:
            continue

        request_name, level = next(iter(signatures))
        markers.add("command=spin")
        markers.add(f"purchased_feature={request_name}")
        if level:
            markers.add(f"purchased_feature_level={level}")
        route["wire_markers"] = sorted(markers)
        route["status"] = "NETWORK_INFERRED"
        route["interface_role"] = "network_action"
        route["confidence"] = "HIGH"


def _api_v2_static_buy_features(
    evidence: EvidenceBundle,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for script in evidence.scripts:
        source = str(script.text or "")
        start = 0
        while True:
            match = re.search(
                r'buy_features\s*:\s*\{\s*features\s*:\s*\[',
                source[start:],
            )
            if match is None:
                break
            array_start = start + match.end() - 1
            body = _balanced_js_array(source, array_start, max_chars=12000)
            start = array_start + max(1, len(body))
            if not body:
                continue

            for obj in re.finditer(r'\{([^{}]{1,900})\}', body):
                text = obj.group(1)
                request = re.search(
                    r'\brequestName\s*:\s*["\']([^"\']+)["\']',
                    text,
                )
                name = re.search(
                    r'\bname\s*:\s*["\']([^"\']+)["\']',
                    text,
                )
                level = re.search(
                    r'\blevel\s*:\s*["\']?([A-Za-z0-9_.-]+)["\']?',
                    text,
                )
                variant = re.search(r'\bvariantShift\s*:', text)
                if request is None or name is None or variant is not None:
                    continue
                row = (
                    str(name.group(1)),
                    str(request.group(1)),
                    str(level.group(1)) if level else "",
                )
                if row in seen:
                    continue
                seen.add(row)
                rows.append(
                    {
                        "name": row[0],
                        "request_name": row[1],
                        "level": row[2],
                    }
                )
    return rows


def _balanced_js_array(
    text: str,
    start: int,
    *,
    max_chars: int,
) -> str:
    if start < 0 or start >= len(text) or text[start] != "[":
        return ""

    depth = 0
    quote = ""
    escaped = False
    end = min(len(text), start + max_chars)
    for index in range(start, end):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'", "`"}:
            quote = char
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _feature_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _seed_hyperhive_spin_routes(
    routes: list[dict[str, Any]],
) -> None:
    for route in routes:
        if route.get("semantic") != "SPIN":
            continue
        if route.get("interface_role") == "opener":
            continue
        if route.get("status") == "NETWORK_OBSERVED":
            continue
        text = f"{route.get('control') or ''} {route.get('handler') or ''}"
        if not re.search(r"spin", text, re.IGNORECASE):
            continue

        markers = {
            str(item)
            for item in route.get("wire_markers") or []
        }
        markers.add("method=play")
        route["wire_markers"] = sorted(markers)
        route["status"] = "NETWORK_INFERRED"
        route["interface_role"] = "network_action"
        route["confidence"] = "MEDIUM"


def _select_base_spin_browser_fallback(
    routes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Choose one explicit client spin handler as an API-v2 recovery probe."""
    candidates: list[dict[str, Any]] = []
    for route in routes:
        if route.get("semantic") != "SPIN":
            continue
        if route.get("status") == "NETWORK_OBSERVED":
            continue
        if route.get("interface_role") not in {"client_control", "network_action"}:
            continue
        control = str(route.get("control") or "").strip()
        handler = str(route.get("handler") or "").strip()
        if not control or not handler:
            continue
        if not re.search(r"spin", f"{control} {handler}", re.IGNORECASE):
            continue
        candidates.append(route)

    if not candidates:
        return None

    def rank(route: dict[str, Any]) -> tuple[int, int, str]:
        control = str(route.get("control") or "")
        handler = str(route.get("handler") or "")
        score = 0
        if re.search(r"spin", control, re.IGNORECASE):
            score += 20
        if re.search(r"spin", handler, re.IGNORECASE):
            score += 20
        if str(route.get("confidence") or "").upper() == "HIGH":
            score += 5
        return (score, len(handler), str(route.get("route_id") or ""))

    return max(candidates, key=rank)


def _select_handler_probe_routes(
    routes: list[dict[str, Any]],
    *,
    max_routes: int = 32,
) -> list[dict[str, Any]]:
    candidates = [
        route
        for route in routes
        if str(route.get("handler") or "").strip()
        and str(route.get("control") or "").strip()
        and route.get("interface_role") == "network_action"
        and route.get("status") != "NETWORK_OBSERVED"
        and route.get("static_wire_complete") is not False
        and route.get("semantic")
        in {
            "SPIN",
            "BUY_BONUS",
            "FREESPIN",
            "RESPIN",
            "PICK",
            "GAME_VARIANT",
            "CONTINUE",
        }
        and (
            route.get("semantic") != "BUY_BONUS"
            or any(
                str(marker).startswith("purchased_feature=")
                for marker in route.get("wire_markers") or []
            )
        )
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
    static_fields = route.get("static_request_fields")
    if isinstance(static_fields, dict):
        for exchange in evidence.http:
            if (
                exchange.response_status is None
                or not 200 <= exchange.response_status < 400
            ):
                continue
            if _static_request_matches(
                exchange.request_body,
                static_fields,
            ):
                return True
        return False

    wanted = set(route.get("wire_markers") or [])
    semantic = str(route.get("semantic") or "")
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
            if not specific:
                continue
            purchased = [
                marker
                for marker in observed
                if str(marker).startswith("purchased_feature=")
            ]
            if purchased and specific <= observed:
                return True
            continue

        if wanted and wanted <= observed:
            return True
    return False


def _static_request_matches(
    value: Any,
    expected: dict[str, Any],
) -> bool:
    if not isinstance(value, dict):
        return False
    params = value.get("params")
    req = params.get("req") if isinstance(params, dict) else None
    if not isinstance(req, dict):
        return False

    for key, wanted in expected.items():
        if isinstance(wanted, str) and wanted.startswith("$"):
            if key not in req:
                return False
            continue
        if req.get(key) != wanted:
            return False
    return True


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

def _require_runtime_identity(
    requested_url: str,
    evidence: EvidenceBundle,
) -> None:
    expected_slug = _public_game_slug(requested_url)
    expected = _identity_key(expected_slug)
    if not expected:
        return

    observed: set[str] = set()
    for exchange in evidence.http:
        parsed = urlsplit(str(exchange.url or ""))
        host = (parsed.hostname or "").casefold()
        parts = [part for part in parsed.path.split("/") if part]
        lowered = [part.casefold() for part in parts]

        if "api" in lowered:
            index = lowered.index("api")
            if index + 1 < len(parts):
                candidate = _identity_key(parts[index + 1])
                if candidate and candidate not in {"api", "v1", "v2"}:
                    observed.add(candidate)

        if (
            host.endswith(".demo.bgaming-network.com")
            and host != "demo.bgaming-network.com"
        ):
            label = host.removesuffix(".demo.bgaming-network.com")
            candidate = _identity_key(label)
            if candidate:
                observed.add(candidate)

    if observed and expected not in observed:
        raise ValueError(
            "BGaming runtime does not match requested public game: "
            f"expected={expected_slug}, observed={','.join(sorted(observed))}"
        )


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
