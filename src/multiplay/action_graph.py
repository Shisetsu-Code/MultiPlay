from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .har_map import build_har_map

_FUNC_PATTERNS = (
    re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]{1,80})\s*\([^()]{0,250}\)\s*\{"),
    re.compile(
        r"\b([A-Za-z_$][A-Za-z0-9_$]{1,80})\s*:\s*function\s*"
        r"\([^)]{0,250}\)\s*\{"
    ),
    re.compile(
        r"\b([A-Za-z_$][A-Za-z0-9_$]{1,80})\s*=\s*function\s*"
        r"\([^)]{0,250}\)\s*\{"
    ),
)

_INTEREST_RE = re.compile(
    r"(spin|buy|bonus|feature|request|play|gamble|select|pick|collect|send|fetch|"
    r"post|command|continue|respin|freespin|choose|api|round|bet)",
    re.IGNORECASE,
)

_CONTEXT_NAMES = {
    "all",
    "classes",
    "currentScene",
    "data",
    "game",
    "parent",
    "rootScene",
    "SharedAPI",
    "Sound",
    "this",
}

_CALL_NOISE = {
    "Array",
    "Boolean",
    "Date",
    "JSON",
    "Map",
    "Math",
    "Number",
    "Object",
    "Promise",
    "Set",
    "String",
    "apply",
    "bind",
    "call",
    "catch",
    "clearTimeout",
    "emit",
    "filter",
    "find",
    "forEach",
    "loadPrefab",
    "map",
    "parseInt",
    "push",
    "resolve",
    "schedule",
    "setTimeout",
    "some",
    "then",
    "track",
    "update",
}

_UI_ONLY_RE = re.compile(
    r"(settings|rules|paytable|history|sound|music|mute|home|info|close|hide|show|"
    r"toggle|popup|modal)",
    re.IGNORECASE,
)

_SEMANTICS = (
    ("BUY_BONUS", re.compile(r"(buy.*bonus|bonus.*buy|buy.?feature)", re.IGNORECASE)),
    ("FREESPIN", re.compile(r"(free.?spin|freespin)", re.IGNORECASE)),
    ("RESPIN", re.compile(r"respin", re.IGNORECASE)),
    ("AUTOSPIN", re.compile(r"autospin", re.IGNORECASE)),
    ("SPIN", re.compile(r"(^|[-_.])spin($|[-_.])|spinClick|\bspin\b", re.IGNORECASE)),
    ("GAMBLE", re.compile(r"gamble", re.IGNORECASE)),
    ("COLLECT", re.compile(r"collect", re.IGNORECASE)),
    ("PICK", re.compile(r"(pick|choose|select.?bonus|choice)", re.IGNORECASE)),
    ("BET", re.compile(r"(bet-up|bet-down|increaseBet|decreaseBet|bet-list)", re.IGNORECASE)),
    ("GAME_VARIANT", re.compile(r"(setCurrentGame|game[1-9])", re.IGNORECASE)),
    ("CONTINUE", re.compile(r"(continue|next|finish|close)", re.IGNORECASE)),
)


def build_action_graph(
    path: str | Path,
    *,
    include_all: bool = False,
    max_depth: int = 5,
) -> dict[str, Any]:
    source_path = Path(path)
    report = build_har_map(source_path)
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    entries = raw.get("log", {}).get("entries")
    if not isinstance(entries, list):
        raise TypeError("Invalid HAR: missing log.entries")

    scripts = _provider_scripts(entries, report)
    definitions = _function_index(scripts)
    observed = [
        item
        for item in report.get("actions", [])
        if item.get("kind") == "observed_request"
    ]

    routes: list[dict[str, Any]] = []
    for control in _control_roots(report):
        route = _resolve_control(
            control,
            definitions=definitions,
            observed=observed,
            max_depth=max_depth,
        )
        if include_all or _keep_route(route):
            routes.append(route)

    routes = _dedupe_routes(routes)
    routes.sort(
        key=lambda item: (
            _route_rank(item),
            item.get("semantic", ""),
            item.get("control", "").casefold(),
            item["route_id"],
        )
    )

    return {
        "schema": "multiplay/action-graph/v1",
        "source": str(source_path),
        "script_count": len(scripts),
        "function_count": sum(len(items) for items in definitions.values()),
        "route_count": len(routes),
        "routes": routes,
        "endpoints": report.get("endpoints", []),
    }


def render_action_graph(
    graph: dict[str, Any],
    *,
    route_id: str | None = None,
) -> str:
    if route_id:
        route = next(
            (
                item
                for item in graph.get("routes", [])
                if item.get("route_id") == route_id
            ),
            None,
        )
        if route is None:
            raise KeyError(f"unknown route_id: {route_id}")
        endpoint_ids = set(route.get("endpoint_ids") or [])
        endpoints = [
            item
            for item in graph.get("endpoints", [])
            if item.get("endpoint_id") in endpoint_ids
        ]
        return json.dumps(
            {"route": route, "endpoints": endpoints},
            indent=2,
            ensure_ascii=False,
        ) + "\n"

    lines = [
        f"HAR: {graph.get('source', '')}",
        "",
        "GAME ACTION ROUTES",
    ]
    for item in graph.get("routes", []):
        markers = ", ".join(item.get("wire_markers") or []) or "-"
        chain = " -> ".join(item.get("chain") or []) or "-"
        endpoints = ",".join(item.get("endpoint_ids") or []) or "-"
        replay = item.get("replay_action_id") or "-"
        lines.append(
            f"{item['route_id']}  {item['semantic']:<12} "
            f"{item['status']:<18} {item['control'][:32]:<32}"
        )
        lines.append(f"      handler: {item.get('handler') or '-'}")
        lines.append(f"      chain:   {chain}")
        lines.append(f"      wire:    {markers}")
        lines.append(f"      endpoint:{endpoints}  replay:{replay}")

    lines.extend(
        [
            "",
            "Detalle:",
            "  multiplay har-actions <archivo.har> --route <route_id>",
        ]
    )
    return "\n".join(lines) + "\n"


def _control_roots(report: dict[str, Any]) -> list[dict[str, Any]]:
    controls = []
    for item in report.get("actions", []):
        if item.get("kind") not in {"declared_button", "html_control"}:
            continue
        label = str(item.get("label") or "").strip()
        handler = str(item.get("handler") or item.get("handler_hint") or "").strip()
        if label or handler:
            controls.append(item)
    return controls


def _provider_scripts(
    entries: list[dict[str, Any]],
    report: dict[str, Any],
) -> list[tuple[str, str]]:
    roots = {
        _host_root(urlsplit(str(item.get("endpoint_template") or "")).hostname or "")
        for item in report.get("endpoints", [])
    }
    roots.discard("")

    scripts: list[tuple[str, str]] = []
    for entry in entries:
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        content = response.get("content") or {}
        text = content.get("text")
        if not isinstance(text, str) or not text:
            continue

        url = str(request.get("url") or "")
        path = urlsplit(url).path.casefold()
        mime = str(content.get("mimeType") or "").casefold()
        if not (
            "javascript" in mime
            or "ecmascript" in mime
            or path.endswith((".js", ".mjs"))
        ):
            continue

        host = (urlsplit(url).hostname or "").casefold()
        root = _host_root(host)
        if roots and root not in roots:
            continue
        scripts.append((url, text))
    return scripts


def _function_index(
    scripts: list[tuple[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source, text in scripts:
        seen: set[tuple[int, str]] = set()
        for pattern in _FUNC_PATTERNS:
            for match in pattern.finditer(text):
                name = str(match.group(1))
                if name in {"if", "for", "while", "catch", "switch", "function"}:
                    continue
                key = (match.start(), name)
                if key in seen:
                    continue
                seen.add(key)

                brace = text.find("{", match.start(), match.end() + 2)
                if brace < 0:
                    continue
                body = _balanced_body(text, brace, max_chars=16000)
                if not body:
                    continue

                markers = sorted(_protocol_markers(body))
                calls = _called_symbols(body)
                protocol_hint = _protocol_hint(body)
                score = (
                    len(markers) * 100
                    + (40 if protocol_hint else 0)
                    + sum(6 for call in calls if _INTEREST_RE.search(call))
                    + min(len(body) // 700, 12)
                )
                index[name].append(
                    {
                        "source": source,
                        "body": body,
                        "wire_markers": markers,
                        "calls": calls,
                        "protocol_hint": protocol_hint,
                        "score": score,
                    }
                )

    for items in index.values():
        items.sort(
            key=lambda item: (
                item["score"],
                len(item["wire_markers"]),
                len(item["body"]),
            ),
            reverse=True,
        )
    return dict(index)


def _resolve_control(
    control: dict[str, Any],
    *,
    definitions: dict[str, list[dict[str, Any]]],
    observed: list[dict[str, Any]],
    max_depth: int,
) -> dict[str, Any]:
    label = str(control.get("label") or "")
    handler = str(control.get("handler") or control.get("handler_hint") or "")
    roots = _handler_symbols(handler, definitions)

    paths: list[dict[str, Any]] = []
    for root in roots[:4]:
        paths.extend(
            _trace_symbol(
                root,
                definitions=definitions,
                max_depth=max_depth,
                visited=(),
            )
        )

    paths.sort(
        key=lambda item: (
            len(item.get("wire_markers") or []),
            1 if item.get("protocol_hint") else 0,
            item.get("score", 0),
            -len(item.get("chain") or []),
        ),
        reverse=True,
    )
    best = paths[0] if paths else {
        "chain": roots,
        "wire_markers": [],
        "protocol_hint": False,
        "score": 0,
    }

    markers = {str(item) for item in control.get("wire_markers") or []}
    markers.update(str(item) for item in best.get("wire_markers") or [])

    observed_match = _match_observed(
        label=label,
        handler=handler,
        markers=markers,
        observed=observed,
    )
    if observed_match is not None:
        markers.update(str(item) for item in observed_match.get("wire_markers") or [])

    status = _route_status(
        label=label,
        handler=handler,
        markers=markers,
        protocol_hint=bool(best.get("protocol_hint")),
        observed_match=observed_match,
    )
    semantic = _semantic(label, handler, best.get("chain") or [], markers)
    endpoint_ids = (
        list(observed_match.get("endpoint_ids") or [])
        if observed_match is not None
        else []
    )
    replay_action_id = (
        str(observed_match.get("action_id") or "")
        if observed_match is not None
        else ""
    )

    fingerprint = json.dumps(
        {
            "control": label,
            "handler": handler,
            "semantic": semantic,
            "chain": best.get("chain") or [],
            "markers": sorted(markers),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    route_id = "R" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8].upper()

    return {
        "route_id": route_id,
        "semantic": semantic,
        "status": status,
        "control": label,
        "handler": handler,
        "occurrence_source": str(control.get("source") or ""),
        "chain": list(best.get("chain") or roots),
        "wire_markers": sorted(markers),
        "endpoint_ids": endpoint_ids,
        "replay_action_id": replay_action_id,
        "confidence": _confidence(status, best, observed_match),
        "trace_source": str(best.get("source") or ""),
        "trace_snippet": str(best.get("snippet") or "")[:1000],
    }


def _trace_symbol(
    name: str,
    *,
    definitions: dict[str, list[dict[str, Any]]],
    max_depth: int,
    visited: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not name or name in visited or len(visited) >= max_depth:
        return []
    items = definitions.get(name) or []
    if not items:
        return []

    results: list[dict[str, Any]] = []
    for definition in items[:3]:
        own_markers = set(definition.get("wire_markers") or [])
        own_hint = bool(definition.get("protocol_hint"))
        children: list[dict[str, Any]] = []

        for call in definition.get("calls", [])[:12]:
            if call == name or call in visited:
                continue
            children.extend(
                _trace_symbol(
                    call,
                    definitions=definitions,
                    max_depth=max_depth,
                    visited=(*visited, name),
                )
            )

        children.sort(
            key=lambda item: (
                len(item.get("wire_markers") or []),
                1 if item.get("protocol_hint") else 0,
                item.get("score", 0),
            ),
            reverse=True,
        )

        for child in children[:3]:
            markers = own_markers | set(child.get("wire_markers") or [])
            results.append(
                {
                    "chain": [name, *list(child.get("chain") or [])],
                    "wire_markers": sorted(markers),
                    "protocol_hint": own_hint or bool(child.get("protocol_hint")),
                    "score": int(definition.get("score") or 0)
                    + int(child.get("score") or 0),
                    "source": (
                        definition.get("source")
                        if own_markers or own_hint
                        else child.get("source")
                    ),
                    "snippet": (
                        definition.get("body")
                        if own_markers or own_hint
                        else child.get("snippet")
                    ),
                }
            )

        results.append(
            {
                "chain": [name],
                "wire_markers": sorted(own_markers),
                "protocol_hint": own_hint,
                "score": int(definition.get("score") or 0),
                "source": definition.get("source"),
                "snippet": definition.get("body"),
            }
        )

    return results


def _handler_symbols(
    handler: str,
    definitions: dict[str, list[dict[str, Any]]],
) -> list[str]:
    tokens = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", handler or "")
    values: list[str] = []

    for token in reversed(tokens):
        if token in _CONTEXT_NAMES or token not in definitions:
            continue
        if _INTEREST_RE.search(token):
            values.append(token)

    if not values:
        for token in reversed(tokens):
            if token in _CONTEXT_NAMES or token not in definitions:
                continue
            values.append(token)
            break

    return list(dict.fromkeys(values))


def _called_symbols(body: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(
        r"(?:\.|\b)([A-Za-z_$][A-Za-z0-9_$]{1,80})\s*(?:\(|\x60)",
        body,
    ):
        name = str(match.group(1))
        if name in _CALL_NOISE:
            continue
        values.append(name)

    unique = list(dict.fromkeys(values))
    unique.sort(
        key=lambda name: (
            0 if _INTEREST_RE.search(name) else 1,
            len(name),
            name,
        )
    )
    return unique[:30]


def _protocol_markers(text: str) -> set[str]:
    out: set[str] = set()
    patterns = (
        ("command", re.compile(r'["\']?command["\']?\s*:\s*["\']([^"\']+)["\']')),
        (
            "purchased_feature",
            re.compile(r'["\']?purchased_feature["\']?\s*:\s*["\']([^"\']+)["\']'),
        ),
        (
            "purchased_feature_level",
            re.compile(
                r'["\']?purchased_feature_level["\']?\s*:\s*'
                r'["\']?([^,"\'\}\s]+)'
            ),
        ),
        ("action", re.compile(r'["\']?action["\']?\s*:\s*["\']([^"\']+)["\']')),
        ("bet_type", re.compile(r'["\']?bet_type["\']?\s*:\s*["\']([^"\']+)["\']')),
    )
    for key, pattern in patterns:
        for match in pattern.finditer(text):
            value = str(match.group(1) or "").strip()
            if value:
                out.add(f"{key}={value}")

    for match in re.finditer(
        r'requestCommand\(\s*["\']([^"\']+)["\']',
        text,
    ):
        out.add(f"command={match.group(1)}")

    assignment = re.compile(
        r'(?:let|const|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*'
        r'["\']([^"\']+)["\'][\s\S]{0,900}?requestCommand\(\1'
    )
    for match in assignment.finditer(text):
        out.add(f"command={match.group(2)}")

    if re.search(r"(?:\.|\b)api\.play\(", text):
        out.add("method=play")

    for match in re.finditer(
        r'["\']?method["\']?\s*:\s*["\'](init|play)["\']',
        text,
        flags=re.IGNORECASE,
    ):
        out.add(f"method={match.group(1).casefold()}")

    return out


def _protocol_hint(text: str) -> bool:
    return bool(
        re.search(
            r"(requestCommand\(|requestURL\(|(?:\.|\b)api\.play\(|"
            r"\bfetch\(|XMLHttpRequest|jsonrpc|window\.__OPTIONS__\.api)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _match_observed(
    *,
    label: str,
    handler: str,
    markers: set[str],
    observed: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    semantic_tokens = _semantic_tokens(f"{label} {handler}")

    for item in observed:
        observed_markers = {str(value) for value in item.get("wire_markers") or []}
        shared = markers & observed_markers
        score = len(shared) * 100

        if not shared:
            for marker in observed_markers:
                if "=" not in marker:
                    continue
                _key, value = marker.split("=", 1)
                value_tokens = _semantic_tokens(value)
                if value_tokens and value_tokens <= semantic_tokens:
                    score += 40
                elif semantic_tokens and semantic_tokens <= value_tokens:
                    score += 25

        if score:
            candidates.append((score, item))

    if not candidates:
        return None
    candidates.sort(
        key=lambda pair: (
            pair[0],
            len(pair[1].get("wire_markers") or []),
        ),
        reverse=True,
    )
    return candidates[0][1]


def _route_status(
    *,
    label: str,
    handler: str,
    markers: set[str],
    protocol_hint: bool,
    observed_match: dict[str, Any] | None,
) -> str:
    if observed_match is not None:
        return "NETWORK_OBSERVED"
    if markers or protocol_hint:
        return "NETWORK_INFERRED"
    if _UI_ONLY_RE.search(f"{label} {handler}"):
        return "UI_ONLY"
    return "CLIENT_OR_UNKNOWN"


def _semantic(
    label: str,
    handler: str,
    chain: list[str],
    markers: set[str],
) -> str:
    text = " ".join([label, handler, *chain, *sorted(markers)])
    for name, pattern in _SEMANTICS:
        if pattern.search(text):
            return name
    return "OTHER"


def _semantic_tokens(value: str) -> set[str]:
    parts = re.findall(r"[A-Za-z0-9]+", str(value).replace("_", " ").replace("-", " "))
    return {
        part.casefold()
        for part in parts
        if len(part) >= 2 and part.casefold() not in {"btn", "button", "common", "ui"}
    }


def _confidence(
    status: str,
    best: dict[str, Any],
    observed_match: dict[str, Any] | None,
) -> str:
    if observed_match is not None:
        return "HIGH"
    if status == "NETWORK_INFERRED" and best.get("wire_markers"):
        return "HIGH"
    if status == "NETWORK_INFERRED":
        return "MEDIUM"
    if status == "UI_ONLY":
        return "MEDIUM"
    return "LOW"


def _keep_route(route: dict[str, Any]) -> bool:
    if route.get("status") in {"NETWORK_OBSERVED", "NETWORK_INFERRED"}:
        return True
    return route.get("semantic") in {
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


def _route_rank(route: dict[str, Any]) -> int:
    status = str(route.get("status") or "")
    if status == "NETWORK_OBSERVED":
        return 0
    if status == "NETWORK_INFERRED":
        return 1
    if status == "CLIENT_OR_UNKNOWN":
        return 2
    return 3


def _dedupe_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for route in routes:
        key = (
            str(route.get("control") or ""),
            str(route.get("handler") or ""),
            str(route.get("semantic") or ""),
        )
        current = grouped.get(key)
        if current is None or _route_rank(route) < _route_rank(current):
            route = dict(route)
            route["occurrences"] = 1
            grouped[key] = route
        else:
            current["occurrences"] = int(current.get("occurrences") or 1) + 1
            current["wire_markers"] = sorted(
                set(current.get("wire_markers") or [])
                | set(route.get("wire_markers") or [])
            )
            current["endpoint_ids"] = sorted(
                set(current.get("endpoint_ids") or [])
                | set(route.get("endpoint_ids") or [])
            )
    return list(grouped.values())


def _balanced_body(text: str, start: int, *, max_chars: int) -> str:
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

        if char in {'"', "'", "\x60"}:
            quote = char
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:end]


def _host_root(host: str) -> str:
    labels = [part for part in str(host or "").casefold().split(".") if part]
    return ".".join(labels[-2:]) if len(labels) >= 2 else ".".join(labels)
