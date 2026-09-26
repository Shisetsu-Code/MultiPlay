from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .probe import _HttpSession

_ENGINE_ROLES = {
    "client.min.js",
    "common.min.js",
    "game.min.js",
    "integration.min.js",
}


class _ScriptSrcParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.urls: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "script":
            return
        mapping = {str(key): str(value or "") for key, value in attrs}
        src = mapping.get("src", "").strip()
        if src:
            self.urls.append(urljoin(self.base_url, src))


def collect_hyperhive_contract_scripts(
    session: _HttpSession,
    *,
    inner_html: str,
    inner_url: str,
    outer_url: str,
    timeout_s: float,
) -> list[tuple[str, str]]:
    candidates = _html_script_urls(inner_html, inner_url)
    candidates.extend(_dynamic_loader_urls(inner_html, inner_url))

    for url in list(dict.fromkeys(candidates)):
        if "fileshashes.js" not in urlsplit(url).path.casefold():
            continue
        try:
            result = session.get(
                url,
                timeout_s=timeout_s,
                headers={"Referer": inner_url},
            )
        except RuntimeError:
            continue
        candidates.extend(_manifest_script_urls(result.url, result.text))

    for fallback in (
        urljoin(inner_url, "client.min.js"),
        urljoin(inner_url, "game/game.min.js"),
        urljoin(inner_url, "game/integration.min.js"),
    ):
        candidates.append(fallback)

    queue = list(dict.fromkeys(candidates))
    seen: set[str] = set()
    contracts: list[tuple[str, str]] = []
    total = 0
    max_bytes = 12 * 1024 * 1024

    while queue and len(seen) < 40 and total < max_bytes:
        script_url = queue.pop(0)
        if script_url in seen or not _provider_owned(script_url, outer_url):
            continue
        seen.add(script_url)

        try:
            result = session.get(
                script_url,
                timeout_s=timeout_s,
                headers={"Referer": inner_url},
            )
        except RuntimeError:
            continue

        text = result.text or ""
        if not text:
            continue
        size = len(text.encode("utf-8", errors="replace"))
        if total + size > max_bytes:
            continue
        total += size

        lower = text.casefold()
        basename = urlsplit(result.url).path.rsplit("/", 1)[-1].casefold()
        if (
            basename in _ENGINE_ROLES
            or any(
                marker in lower
                for marker in (
                    "jsonrpc",
                    "state_lock",
                    "bet_type",
                    "custom_req",
                    "purchased_feature",
                    "formattedrequest",
                )
            )
        ):
            contracts.append((result.url, text))

        for child in _static_js_references(text, result.url):
            if child not in seen and _provider_owned(child, outer_url):
                queue.append(child)

    if not contracts:
        raise ValueError(
            "BGaming HyperHive client scripts exposed no usable wire contract."
        )
    return contracts


def _html_script_urls(html: str, base_url: str) -> list[str]:
    parser = _ScriptSrcParser(base_url)
    parser.feed(html or "")
    return parser.urls


def _dynamic_loader_urls(html: str, base_url: str) -> list[str]:
    substitutions = {
        "versionPath": _literal_assignment(html, "versionPath"),
        "gamePath": _literal_assignment(html, "gamePath"),
    }
    out: list[str] = []
    for match in re.finditer(
        r"([\"'\x60])([^\"'\x60]{1,400}\.js)\1",
        html or "",
    ):
        raw = str(match.group(2) or "").strip()
        unresolved = False
        for name, value in substitutions.items():
            marker = "$" + "{" + name + "}"
            if marker not in raw:
                continue
            if not value:
                unresolved = True
                break
            raw = raw.replace(marker, value)
        if unresolved or "$" + "{" in raw:
            continue
        out.append(urljoin(base_url, raw))
    return list(dict.fromkeys(out))


def _manifest_script_urls(manifest_url: str, text: str) -> list[str]:
    out: list[str] = []
    for match in re.finditer(
        r'["\']fileName["\']\s*:\s*["\']([^"\']+\.js)["\']\s*,\s*'
        r'["\']hash["\']\s*:\s*["\']([A-Fa-f0-9]{8,128})["\']',
        text or "",
    ):
        base = urljoin(manifest_url, match.group(1))
        out.append(
            base
            + ("&" if "?" in base else "?")
            + "key="
            + match.group(2)
        )
    return list(dict.fromkeys(out))


def _static_js_references(text: str, base_url: str) -> list[str]:
    out: list[str] = []
    for pattern in (
        r'["\']([^"\']+\.js(?:\?[^"\']*)?)["\']',
        r'import\(\s*["\']([^"\']+)["\']\s*\)',
    ):
        for raw in re.findall(pattern, text or ""):
            value = str(raw or "").strip()
            if value:
                out.append(urljoin(base_url, value))
    return list(dict.fromkeys(out))


def _provider_owned(url: str, outer_url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    outer_host = (urlsplit(outer_url).hostname or "").casefold()
    return bool(
        host
        and (
            host == outer_host
            or host == "bgaming-network.com"
            or host.endswith(".bgaming-network.com")
        )
    )


def _literal_assignment(text: str, name: str) -> str:
    match = re.search(
        rf"\b(?:var|let|const)?\s*{re.escape(name)}\s*=\s*['\"]([^'\"]{{0,160}})['\"]",
        text or "",
    )
    return str(match.group(1)) if match else ""
