from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ...models import EvidenceBundle

_ARRAY_RE_TEMPLATE = (
    r"\[(?P<body>(?:\s*[\"']{prefix}[A-Za-z0-9_-]+[\"']\s*,?){2,})\]"
)


def extract_switchable_variants(
    evidence: EvidenceBundle,
    parent_identifier: str,
) -> list[str]:
    parent = str(parent_identifier or "").strip()
    if not parent:
        return []

    pattern = re.compile(
        _ARRAY_RE_TEMPLATE.format(prefix=re.escape(parent)),
        flags=re.IGNORECASE,
    )
    item_pattern = re.compile(
        r"[\"'](" + re.escape(parent) + r"[A-Za-z0-9_-]+)[\"']",
        flags=re.IGNORECASE,
    )

    candidates: list[list[str]] = []
    for script in evidence.scripts:
        for match in pattern.finditer(script.text):
            values = [item.group(1) for item in item_pattern.finditer(match.group("body"))]
            values = list(dict.fromkeys(values))
            if len(values) >= 2:
                candidates.append(values)

    if not candidates:
        return []

    candidates.sort(key=lambda values: (len(values), sum(map(len, values))), reverse=True)
    return candidates[0]


def switchable_child_url(parent_url: str, identifier: str) -> str:
    child = str(identifier or "").strip()
    if not child or not re.fullmatch(r"[A-Za-z0-9_-]+", child):
        raise ValueError("invalid switchable child identifier")

    parsed = urlsplit(str(parent_url or ""))
    host = parsed.hostname or ""
    if not host:
        raise ValueError("switchable parent URL has no host")

    netloc = parsed.netloc
    return urlunsplit(
        (
            parsed.scheme or "https",
            netloc,
            f"/play/{child}/FUN",
            "",
            "",
        )
    )


def route_child_index(route: dict[str, Any]) -> int | None:
    handler = str(route.get("handler") or "")
    if "setCurrentGame" not in handler or "`" not in handler:
        return None
    raw = handler.split("`", 1)[1].split(",", 1)[0].strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None
