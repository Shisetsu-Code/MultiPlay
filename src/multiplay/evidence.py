from __future__ import annotations

import base64
import binascii
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from .models import EvidenceBundle, HttpExchange, ScriptEvidence

_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "x-api-key",
}
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:token|session|csrf|secret|password|authorization|cookie|api[_-]?key)(?:$|_)",
    re.IGNORECASE,
)
_SCRIPT_MIMES = ("javascript", "ecmascript")


class HarError(ValueError):
    pass


def redact(value: Any) -> Any:
    """Redact secret values while preserving field names and protocol shape."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            name = str(key)
            out[name] = "<redacted>" if _SENSITIVE_KEY_RE.search(name) else redact(child)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def load_har(path: str | Path) -> EvidenceBundle:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = raw.get("log", {}).get("entries")
    if not isinstance(entries, list):
        raise HarError("Invalid HAR: missing log.entries")

    bundle = EvidenceBundle(metadata={"source": str(path)})
    for index, entry in enumerate(entries):
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        url = str(request.get("url") or "")
        if not url:
            continue

        content = response.get("content") or {}
        response_body = _response_body(content)
        evidence_id = f"har:http:{index}"
        bundle.http.append(
            HttpExchange(
                evidence_id=evidence_id,
                method=str(request.get("method") or "GET").upper(),
                url=url,
                request_headers=_headers(request.get("headers")),
                request_body=redact(_request_body(request.get("postData"))),
                response_status=_int_or_none(response.get("status")),
                response_headers=_headers(response.get("headers")),
                response_body=redact(response_body),
            )
        )

        mime = str(content.get("mimeType") or "").lower()
        if any(marker in mime for marker in _SCRIPT_MIMES) and isinstance(response_body, str):
            bundle.scripts.append(
                ScriptEvidence(
                    evidence_id=f"har:script:{index}",
                    source=url,
                    text=response_body,
                )
            )

    if not bundle.http:
        raise HarError("HAR has no usable HTTP exchanges")
    return bundle


def _headers(items: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        value = str(item.get("value") or "")
        out[name.lower()] = "<redacted>" if name.lower() in _SENSITIVE_HEADERS else value
    return out


def _request_body(post_data: Any) -> Any:
    if not isinstance(post_data, dict):
        return None

    params = post_data.get("params")
    if isinstance(params, list) and params:
        mapped: dict[str, Any] = {}
        for item in params:
            if isinstance(item, dict) and item.get("name") is not None:
                mapped[str(item["name"])] = item.get("value")
        if mapped:
            return mapped

    return _parse_text_payload(
        post_data.get("text"),
        str(post_data.get("mimeType") or "").lower(),
    )


def _response_body(content: Any) -> Any:
    if not isinstance(content, dict):
        return None
    text = content.get("text")
    if text is None:
        return None
    if content.get("encoding") == "base64":
        try:
            text = base64.b64decode(str(text)).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError):
            return None
    return _parse_text_payload(text, str(content.get("mimeType") or "").lower())


def _parse_text_payload(text: Any, mime: str) -> Any:
    if text is None:
        return None
    text = str(text)
    if not text:
        return ""

    if "json" in mime or text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    if "x-www-form-urlencoded" in mime or ("=" in text and "&" in text):
        parsed = parse_qs(text, keep_blank_values=True)
        if parsed:
            return {k: values[0] if len(values) == 1 else values for k, values in parsed.items()}

    return text


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
