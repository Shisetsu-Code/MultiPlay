from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .endpoints import sanitize_endpoint_url, template_payload
from .evidence import load_har

_EVENT_PATTERNS = (
    re.compile(
        r'\.addEventListener\(\s*["\']'
        r'(click|pointerup|pointerdown|pointertap|tap|mouseup|mousedown)'
        r'["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'\.on\(\s*["\']'
        r'(click|pointerup|pointerdown|pointertap|tap|mouseup|mousedown)'
        r'["\']',
        re.IGNORECASE,
    ),
    re.compile(r'\.onclick\s*=', re.IGNORECASE),
    re.compile(r'\.onpointer(?:up|down)\s*=', re.IGNORECASE),
)

_LABEL_PATTERN = re.compile(
    r'(?:label|text|title|caption|buttonText|ariaLabel|name)\s*[:=]\s*'
    r'["\']([^"\']{1,100})["\']',
    re.IGNORECASE,
)
_STRING_PATTERN = re.compile(r'["\']([^"\']{2,80})["\']')

_WIRE_PATTERNS = (
    ("command", re.compile(r'["\']?command["\']?\s*:\s*["\']([^"\']+)["\']')),
    (
        "purchased_feature",
        re.compile(r'["\']?purchased_feature["\']?\s*:\s*["\']([^"\']+)["\']'),
    ),
    (
        "purchased_feature_level",
        re.compile(r'["\']?purchased_feature_level["\']?\s*:\s*["\']?([^,"\'\}\s]+)'),
    ),
    ("action", re.compile(r'["\']?action["\']?\s*:\s*["\']([^"\']+)["\']')),
    ("method", re.compile(r'["\']?method["\']?\s*:\s*["\']([^"\']+)["\']')),
    ("bet_type", re.compile(r'["\']?bet_type["\']?\s*:\s*["\']([^"\']+)["\']')),
)

_NOISE_STRINGS = {
    "click",
    "pointerup",
    "pointerdown",
    "pointertap",
    "tap",
    "mouseup",
    "mousedown",
    "true",
    "false",
    "null",
    "undefined",
    "function",
    "object",
    "string",
    "number",
    "boolean",
    "play",
    "init",
}


class _HtmlControlParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.source = source
        self.controls: list[dict[str, Any]] = []
        self._active: dict[str, Any] | None = None
        self._depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        mapping = {str(key).casefold(): str(value or "") for key, value in attrs}
        tag_name = tag.casefold()
        role = mapping.get("role", "").casefold()
        control = (
            tag_name == "button"
            or role == "button"
            or (tag_name == "input" and mapping.get("type", "").casefold() in {"button", "submit"})
            or (tag_name == "a" and ("onclick" in mapping or mapping.get("href", "").startswith("javascript:")))
        )

        if self._active is not None:
            self._depth += 1
            return
        if not control:
            return

        label = (
            mapping.get("aria-label")
            or mapping.get("title")
            or mapping.get("value")
            or mapping.get("data-label")
            or mapping.get("name")
            or ""
        ).strip()
        handler = (mapping.get("onclick") or mapping.get("href") or "").strip()
        self._active = {
            "kind": "html_control",
            "source": self.source,
            "event": "click",
            "label": label,
            "handler_hint": handler[:700],
            "wire_markers": sorted(_wire_markers_text(handler)),
            "endpoint_ids": [],
            "confidence": "HIGH" if handler else "MEDIUM",
            "_text": [],
        }
        self._depth = 1

        if tag_name == "input":
            self._finish()

    def handle_data(self, data: str) -> None:
        if self._active is None:
            return
        text = " ".join(str(data).split())
        if text:
            self._active["_text"].append(text)

    def handle_endtag(self, tag: str) -> None:
        if self._active is None:
            return
        self._depth -= 1
        if self._depth <= 0:
            self._finish()

    def _finish(self) -> None:
        if self._active is None:
            return
        if not self._active["label"]:
            self._active["label"] = " ".join(self._active.pop("_text", []))[:120]
        else:
            self._active.pop("_text", None)
        self.controls.append(self._active)
        self._active = None
        self._depth = 0


def build_har_map(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    evidence = load_har(source_path)
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    entries = raw.get("log", {}).get("entries")
    if not isinstance(entries, list):
        raise ValueError("Invalid HAR: missing log.entries")

    endpoints = _endpoint_inventory(evidence)
    endpoint_markers = {
        endpoint["endpoint_id"]: set(endpoint.pop("_wire_markers", []))
        for endpoint in endpoints
    }

    actions: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        content = response.get("content") or {}
        body = _decoded_content(content)
        if not isinstance(body, str) or not body.strip():
            continue

        url = str(request.get("url") or f"har-entry-{index}")
        mime = str(content.get("mimeType") or "").casefold()

        if "html" in mime or "<button" in body.casefold() or "role=\"button\"" in body.casefold():
            parser = _HtmlControlParser(url)
            try:
                parser.feed(body)
            except (TypeError, ValueError):
                pass
            actions.extend(parser.controls)

        if (
            "javascript" in mime
            or "ecmascript" in mime
            or urlsplit(url).path.casefold().endswith((".js", ".mjs"))
        ):
            actions.extend(_javascript_controls(body, url))

    actions.extend(_observed_request_actions(endpoints))
    actions = _dedupe_actions(actions)

    for action in actions:
        _associate_endpoints(action, endpoints, endpoint_markers)
        action["action_id"] = _action_id(action)

    actions.sort(
        key=lambda item: (
            0 if item["kind"] in {"html_control", "js_control"} else 1,
            item.get("label", "").casefold(),
            item["action_id"],
        )
    )

    return {
        "schema": "multiplay/har-map/v1",
        "source": str(source_path),
        "endpoint_count": len(endpoints),
        "action_count": len(actions),
        "endpoints": endpoints,
        "actions": actions,
    }


def render_har_map(report: dict[str, Any], *, action_id: str | None = None) -> str:
    if action_id:
        action = next(
            (item for item in report.get("actions", []) if item.get("action_id") == action_id),
            None,
        )
        if action is None:
            raise KeyError(f"unknown action_id: {action_id}")
        endpoint_ids = set(action.get("endpoint_ids") or [])
        endpoints = [
            item
            for item in report.get("endpoints", [])
            if item.get("endpoint_id") in endpoint_ids
        ]
        return json.dumps(
            {
                "action": action,
                "endpoints": endpoints,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n"

    lines = [
        f"HAR: {report.get('source', '')}",
        "",
        "ENDPOINTS",
    ]
    for item in report.get("endpoints", []):
        statuses = ",".join(str(value) for value in item.get("statuses", [])) or "-"
        lines.append(
            f"{item['endpoint_id']:>4}  {item['method']:<7} "
            f"{item['endpoint_template']}  x{item['count']}  [{statuses}]"
        )

    lines.extend(["", "CONTROLS / ACTIONS"])
    for item in report.get("actions", []):
        label = item.get("label") or "-"
        event = item.get("event") or "-"
        endpoints = ",".join(item.get("endpoint_ids") or []) or "-"
        markers = ", ".join(item.get("wire_markers") or []) or "-"
        lines.append(
            f"{item['action_id']}  {item['kind']:<16} "
            f"{event:<11} {label[:42]:<42} -> {endpoints}"
        )
        if markers != "-":
            lines.append(f"      wire: {markers}")

    lines.extend(
        [
            "",
            "Detalle:",
            "  multiplay har-map <archivo.har> --action <action_id>",
        ]
    )
    return "\n".join(lines) + "\n"


def _endpoint_inventory(evidence) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for exchange in evidence.http:
        endpoint = sanitize_endpoint_url(exchange.url)
        key = (exchange.method, endpoint)
        current = grouped.get(key)
        markers = sorted(_wire_markers_value(exchange.request_body))
        request_format = template_payload(exchange.request_body, request_side=True)

        if current is None:
            current = {
                "method": exchange.method,
                "endpoint_template": endpoint,
                "count": 0,
                "statuses": [],
                "request_formats": [],
                "_wire_markers": [],
            }
            grouped[key] = current

        current["count"] += 1
        if exchange.response_status is not None and exchange.response_status not in current["statuses"]:
            current["statuses"].append(exchange.response_status)

        canonical = json.dumps(
            request_format,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        existing = {
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for item in current["request_formats"]
        }
        if canonical not in existing and len(current["request_formats"]) < 6:
            current["request_formats"].append(request_format)

        current["_wire_markers"] = sorted(
            set(current["_wire_markers"]) | set(markers)
        )

    rows = sorted(
        grouped.values(),
        key=lambda item: (item["endpoint_template"], item["method"]),
    )
    for index, item in enumerate(rows, start=1):
        item["endpoint_id"] = f"E{index:03d}"
        item["statuses"].sort()
    return rows


def _javascript_controls(text: str, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern in _EVENT_PATTERNS:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 900)
            end = min(len(text), match.end() + 1200)
            window = text[start:end]
            event = match.group(1).casefold() if match.lastindex else "click"
            label = _best_label(window)
            markers = sorted(_wire_markers_text(window))
            rows.append(
                {
                    "kind": "js_control",
                    "source": source,
                    "event": event,
                    "label": label,
                    "handler_hint": _compact_snippet(window, match.start() - start),
                    "wire_markers": markers,
                    "endpoint_ids": [],
                    "confidence": "HIGH" if markers else "MEDIUM",
                }
            )
    return rows


def _observed_request_actions(endpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for endpoint in endpoints:
        markers = endpoint.get("_wire_markers") or []
        if not markers:
            continue

        primary = next(
            (
                marker
                for marker in markers
                if marker.startswith(("command=", "purchased_feature=", "action=", "method="))
            ),
            "",
        )
        label = primary.split("=", 1)[1] if "=" in primary else endpoint["endpoint_template"]
        rows.append(
            {
                "kind": "observed_request",
                "source": "HAR network",
                "event": "request",
                "label": label,
                "handler_hint": "",
                "wire_markers": list(markers),
                "endpoint_ids": [endpoint["endpoint_id"]],
                "confidence": "OBSERVED",
            }
        )
    return rows


def _associate_endpoints(
    action: dict[str, Any],
    endpoints: list[dict[str, Any]],
    endpoint_markers: dict[str, set[str]],
) -> None:
    if action.get("endpoint_ids"):
        return

    markers = set(action.get("wire_markers") or [])
    handler = str(action.get("handler_hint") or "")
    matched: list[str] = []

    for endpoint in endpoints:
        endpoint_id = endpoint["endpoint_id"]
        shared = markers & endpoint_markers.get(endpoint_id, set())
        path = urlsplit(endpoint["endpoint_template"]).path
        literal_path_hit = bool(path and len(path) > 1 and path in handler)

        strong_shared = any(
            marker.startswith(
                ("command=", "purchased_feature=", "purchased_feature_level=", "action=", "bet_type=")
            )
            for marker in shared
        )
        if strong_shared or literal_path_hit:
            matched.append(endpoint_id)

    action["endpoint_ids"] = matched


def _wire_markers_value(value: Any) -> set[str]:
    markers: set[str] = set()
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
                markers.add(f"{name}={child}")
            markers.update(_wire_markers_value(child))
    elif isinstance(value, list):
        for child in value:
            markers.update(_wire_markers_value(child))
    return markers


def _wire_markers_text(text: str) -> set[str]:
    markers: set[str] = set()
    for name, pattern in _WIRE_PATTERNS:
        for match in pattern.finditer(text or ""):
            value = str(match.group(1) or "").strip()
            if value:
                markers.add(f"{name}={value}")
    return markers


def _best_label(window: str) -> str:
    candidates = [match.group(1).strip() for match in _LABEL_PATTERN.finditer(window)]
    if not candidates:
        candidates = [match.group(1).strip() for match in _STRING_PATTERN.finditer(window)]

    scored: list[tuple[float, str]] = []
    for value in candidates:
        if not _plausible_label(value):
            continue
        alpha = sum(char.isalpha() for char in value)
        uppercase = sum(char.isupper() for char in value)
        spaces = value.count(" ")
        score = alpha + spaces * 3 + (uppercase / max(1, alpha)) * 8
        scored.append((score, value))

    if not scored:
        return ""
    scored.sort(reverse=True)
    return scored[0][1][:100]


def _plausible_label(value: str) -> bool:
    text = value.strip()
    lowered = text.casefold()
    if lowered in _NOISE_STRINGS:
        return False
    if len(text) < 2 or len(text) > 100:
        return False
    if "://" in text or text.endswith((".js", ".png", ".jpg", ".json", ".css")):
        return False
    if not any(char.isalpha() for char in text):
        return False
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", text) and text.islower():
        return False
    return True


def _compact_snippet(window: str, center: int) -> str:
    left = max(0, center - 280)
    right = min(len(window), center + 520)
    return " ".join(window[left:right].split())[:800]


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in actions:
        key = json.dumps(
            {
                "kind": item.get("kind"),
                "source": item.get("source"),
                "event": item.get("event"),
                "label": item.get("label"),
                "wire_markers": item.get("wire_markers"),
                "handler_hint": item.get("handler_hint"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        out.append(item)
    return out


def _action_id(action: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "kind": action.get("kind"),
            "source": action.get("source"),
            "event": action.get("event"),
            "label": action.get("label"),
            "wire_markers": action.get("wire_markers"),
            "endpoint_ids": action.get("endpoint_ids"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "A" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8].upper()


def _decoded_content(content: Any) -> str | None:
    if not isinstance(content, dict):
        return None
    text = content.get("text")
    if text is None:
        return None
    value = str(text)
    if content.get("encoding") == "base64":
        try:
            value = base64.b64decode(value).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError):
            return None
    return value
