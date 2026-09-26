from __future__ import annotations

import http.cookiejar
import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ...evidence import redact
from ...models import EvidenceBundle, HttpExchange, ScriptEvidence
from .bootstrap import (
    BootstrapOptions,
    extract_bootstrap_options,
    sanitize_bootstrap_options,
    sanitize_session_url,
)


@dataclass(frozen=True, slots=True)
class ProbeMetadata:
    requested_url: str
    launch_url: str
    identifier: str
    bootstrap_available: bool
    init_executed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_url": _safe_public_url(self.requested_url),
            "launch_url": sanitize_session_url(self.launch_url),
            "identifier": self.identifier,
            "bootstrap_available": self.bootstrap_available,
            "init_executed": self.init_executed,
        }


@dataclass(frozen=True, slots=True)
class ProbeResult:
    evidence: EvidenceBundle
    metadata: ProbeMetadata


@dataclass(frozen=True, slots=True)
class _HttpResult:
    status: int
    url: str
    text: str


class _AnchorCollector(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.urls: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        mapping = {str(key): str(value or "") for key, value in attrs}
        raw = ""
        if tag.casefold() == "a":
            raw = mapping.get("href", "")
        elif tag.casefold() == "iframe":
            raw = mapping.get("src", "")
        if raw:
            self.urls.append(urljoin(self.base_url, raw.strip()))


class _HttpSession:
    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(jar))

    def get(self, url: str, *, timeout_s: float) -> _HttpResult:
        return self._request(url, timeout_s=timeout_s)

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout_s: float,
        headers: dict[str, str],
    ) -> _HttpResult:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self._request(
            url,
            timeout_s=timeout_s,
            method="POST",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                **headers,
            },
        )

    def _request(
        self,
        url: str,
        *,
        timeout_s: float,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> _HttpResult:
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/136 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                **dict(headers or {}),
            },
        )
        try:
            with self.opener.open(
                request,
                timeout=max(1.0, float(timeout_s)),
            ) as response:
                return _HttpResult(
                    status=int(response.status),
                    url=response.geturl(),
                    text=response.read().decode("utf-8", errors="replace"),
                )
        except HTTPError as exc:
            safe = sanitize_session_url(exc.geturl() or url)
            raise RuntimeError(f"BGaming probe HTTP {exc.code}: {safe}") from exc
        except URLError as exc:
            raise RuntimeError(
                f"BGaming probe transport error: {type(exc.reason).__name__}"
            ) from exc


def probe_bgaming_demo(
    url: str,
    *,
    timeout_s: float = 30.0,
) -> ProbeResult:
    source = str(url or "").strip()
    if not source:
        raise ValueError("BGaming probe URL is empty.")
    if not _allowed_source(source):
        raise ValueError("BGaming probe accepts only bgaming.com/bgaming-network.com URLs.")

    session = _HttpSession()
    launch = _resolve_demo(session, source, timeout_s=timeout_s)
    safe_launch = sanitize_session_url(launch.url)

    if _is_hyperhive_url(launch.url):
        evidence = EvidenceBundle(
            http=[
                HttpExchange(
                    evidence_id="probe:launch",
                    method="GET",
                    url=safe_launch,
                    response_status=launch.status,
                )
            ],
            metadata={"source": "bgaming-probe"},
        )
        return ProbeResult(
            evidence=evidence,
            metadata=ProbeMetadata(
                requested_url=source,
                launch_url=launch.url,
                identifier="",
                bootstrap_available=False,
                init_executed=False,
            ),
        )

    options = extract_bootstrap_options(launch.text)
    sanitized_options = sanitize_bootstrap_options(options.raw)
    init_payload = {
        "command": "init",
        "extra_data": {
            "round_series_id": int(time.time() * 1000),
        },
    }
    parsed_api = urlsplit(options.api)
    init = session.post_json(
        options.api,
        init_payload,
        timeout_s=timeout_s,
        headers={
            "Origin": f"{parsed_api.scheme}://{parsed_api.netloc}",
            "Referer": launch.url,
            options.csrf_header_name: options.csrf_header_value,
        },
    )
    try:
        init_data = json.loads(init.text)
    except json.JSONDecodeError as exc:
        raise ValueError("BGaming init response is not JSON.") from exc
    if not isinstance(init_data, dict):
        raise TypeError("BGaming init response is not a JSON object.")

    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="probe:init",
                method="POST",
                url=sanitize_session_url(options.api),
                request_headers={
                    "content-type": "application/json",
                    options.csrf_header_name.casefold(): "<redacted>",
                },
                request_body=init_payload,
                response_status=init.status,
                response_headers={},
                response_body=redact(init_data),
            )
        ],
        scripts=[
            ScriptEvidence(
                evidence_id="probe:bootstrap",
                source=safe_launch,
                text=json.dumps(
                    sanitized_options,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        ],
        metadata={"source": "bgaming-probe"},
    )
    return ProbeResult(
        evidence=evidence,
        metadata=ProbeMetadata(
            requested_url=source,
            launch_url=launch.url,
            identifier=options.identifier,
            bootstrap_available=True,
            init_executed=True,
        ),
    )


def _resolve_demo(
    session: _HttpSession,
    source: str,
    *,
    timeout_s: float,
) -> _HttpResult:
    first = session.get(source, timeout_s=timeout_s)
    if _is_demo_url(first.url):
        if _is_hyperhive_url(first.url):
            return first
        try:
            extract_bootstrap_options(first.text)
        except ValueError:
            pass
        else:
            return first

    candidates = _demo_candidates(first.text, first.url)
    for candidate in candidates:
        try:
            result = session.get(candidate, timeout_s=timeout_s)
        except RuntimeError:
            continue
        if not _is_demo_url(result.url):
            continue
        if _is_hyperhive_url(result.url):
            return result
        try:
            extract_bootstrap_options(result.text)
        except ValueError:
            continue
        return result

    raise ValueError("BGaming demo could not be resolved from the supplied URL.")


def _demo_candidates(html: str, base_url: str) -> list[str]:
    parser = _AnchorCollector(base_url)
    parser.feed(html or "")
    values = [
        candidate
        for candidate in parser.urls
        if _is_demo_url(candidate)
    ]

    normalized = (html or "").replace("\\/", "/")
    normalized = normalized.replace("\\u002F", "/").replace("\\u002f", "/")
    for match in re.findall(
        r"https?://(?:[A-Za-z0-9.-]+\.)?bgaming-network\.com/[^\"'<>\s]+",
        normalized,
        flags=re.IGNORECASE,
    ):
        candidate = match.rstrip("),.;]")
        if _is_demo_url(candidate):
            values.append(candidate)

    return list(dict.fromkeys(values))


def _allowed_source(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    return (
        host == "bgaming.com"
        or host.endswith(".bgaming.com")
        or host == "bgaming-network.com"
        or host.endswith(".bgaming-network.com")
    )


def _is_demo_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    if not (
        host == "bgaming-network.com"
        or host.endswith(".bgaming-network.com")
    ):
        return False
    path = parsed.path.casefold()
    return (
        "/play/" in path
        or "/games/" in path
        or path.rstrip("/").endswith("/hyperhive")
    )


def _is_hyperhive_url(url: str) -> bool:
    return urlsplit(url).path.casefold().rstrip("/").endswith("/hyperhive")


def _safe_public_url(url: str) -> str:
    parsed = urlsplit(url)
    if _is_demo_url(url):
        return sanitize_session_url(url)
    return parsed._replace(query="", fragment="").geturl()
