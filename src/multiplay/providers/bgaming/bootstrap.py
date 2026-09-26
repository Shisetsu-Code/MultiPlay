from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_SENSITIVE_KEYS = {
    "play_token",
    "drops_token",
    "profile_token",
    "gamelist_token",
    "challenges_token",
    "quests_token",
    "shop_token",
    "csrfTokenHeaderValue",
}


@dataclass(frozen=True, slots=True)
class BootstrapOptions:
    api: str
    identifier: str
    csrf_header_name: str
    csrf_header_value: str
    raw: dict[str, Any]


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self.scripts: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "script":
            self._in_script = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "script" or not self._in_script:
            return
        self.scripts.append("".join(self._parts))
        self._parts = []
        self._in_script = False


def extract_window_options(html: str) -> dict[str, Any]:
    parser = _ScriptCollector()
    parser.feed(html or "")
    decoder = json.JSONDecoder()

    for script in parser.scripts:
        marker = "window.__OPTIONS__"
        start = script.find(marker)
        if start < 0:
            continue
        equal = script.find("=", start + len(marker))
        if equal < 0:
            continue
        payload = script[equal + 1 :].lstrip()
        try:
            value, _ = decoder.raw_decode(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    raise ValueError("BGaming window.__OPTIONS__ not found.")


def extract_bootstrap_options(html: str) -> BootstrapOptions:
    value = extract_window_options(html)
    api = str(value.get("api") or "").strip()
    identifier = str(value.get("identifier") or "").strip()
    csrf_name = str(value.get("csrfTokenHeaderName") or "").strip()
    csrf_value = str(value.get("csrfTokenHeaderValue") or "").strip()
    if not api or not identifier:
        raise ValueError("BGaming bootstrap missing api/identifier.")
    if not csrf_name or not csrf_value:
        raise ValueError("BGaming bootstrap missing CSRF header data.")
    return BootstrapOptions(
        api=api,
        identifier=identifier,
        csrf_header_name=csrf_name,
        csrf_header_value=csrf_value,
        raw=value,
    )


def sanitize_bootstrap_options(value: Any) -> Any:
    if isinstance(value, list):
        return [sanitize_bootstrap_options(item) for item in value]
    if not isinstance(value, dict):
        return value

    out: dict[str, Any] = {}
    for key, item in value.items():
        lowered = str(key).casefold()
        if key in _SENSITIVE_KEYS or ("token" in lowered and key != "csrfTokenHeaderName"):
            out[str(key)] = "<redacted>"
        elif key in {"api", "websocket_url"}:
            out[str(key)] = sanitize_session_url(str(item))
        else:
            out[str(key)] = sanitize_bootstrap_options(item)
    return out


def sanitize_session_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    if "api" in {segment.casefold() for segment in segments} and len(segments) >= 4:
        segments[-1] = "<session>"
    path = "/" + "/".join(segments) if segments else parts.path
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
