from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..endpoints import sanitize_endpoint_url
from ..models import AnalysisResult, EndpointRecord, EvidenceBundle, ValidationState


HttpPredicate = Callable[[Any], bool]
ActionResolver = Callable[[Any], str]


def successful_http(exchange: Any) -> bool:
    status = getattr(exchange, "response_status", None)
    return isinstance(status, int) and 200 <= status < 400


def host_contains(url: str, *needles: str) -> bool:
    from urllib.parse import urlsplit

    host = (urlsplit(str(url or "")).hostname or "").casefold()
    return any(str(needle or "").casefold() in host for needle in needles if needle)


def scalar_action(body: Any, *keys: str) -> str:
    if not isinstance(body, dict):
        return ""
    for key in keys:
        value = body.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).strip()
            if text:
                return text
    return ""


def nested_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for name, child in value.items():
            if str(name) == key:
                found.append(child)
            found.extend(nested_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(nested_values(child, key))
    return found


def template_value(
    value: Any,
    *,
    request_side: bool,
    sensitive_keys: set[str] | frozenset[str] = frozenset(),
    dynamic_keys: set[str] | frozenset[str] = frozenset(),
) -> Any:
    sensitive = {str(item).casefold() for item in sensitive_keys}
    dynamic = {str(item).casefold() for item in dynamic_keys}

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            name = str(key)
            lowered = name.casefold()
            if request_side and lowered in sensitive:
                out[name] = "<redacted>"
            elif request_side and lowered in dynamic:
                out[name] = f"<dynamic:{name}>"
            else:
                out[name] = template_value(
                    child,
                    request_side=request_side,
                    sensitive_keys=sensitive_keys,
                    dynamic_keys=dynamic_keys,
                )
        return out
    if isinstance(value, list):
        return [
            template_value(
                child,
                request_side=request_side,
                sensitive_keys=sensitive_keys,
                dynamic_keys=dynamic_keys,
            )
            for child in value[:4]
        ]
    if request_side:
        return value
    if value is None:
        return None
    if isinstance(value, bool):
        return "<bool>"
    if isinstance(value, (int, float)):
        return "<number>"
    if isinstance(value, str):
        return "<string>"
    return f"<{type(value).__name__}>"


def http_endpoint_records(
    *,
    provider: str,
    evidence: EvidenceBundle,
    analysis: AnalysisResult,
    source_ref: str,
    environment: str,
    predicate: HttpPredicate,
    action_of: ActionResolver,
    sensitive_keys: set[str] | frozenset[str] = frozenset(),
    dynamic_keys: set[str] | frozenset[str] = frozenset(),
    notes: tuple[str, ...] = (),
) -> list[EndpointRecord]:
    del analysis
    records: list[EndpointRecord] = []
    seen: set[tuple[str, str, str]] = set()

    for exchange in evidence.http:
        if not predicate(exchange):
            continue
        action = str(action_of(exchange) or "").strip() or "request"
        endpoint = sanitize_endpoint_url(exchange.url)
        key = (exchange.method.upper(), endpoint, action)
        if key in seen:
            continue
        seen.add(key)

        demo_state = ValidationState.OBSERVED
        live_state = ValidationState.UNKNOWN
        if environment == "live":
            live_state = ValidationState.OBSERVED

        records.append(
            EndpointRecord(
                provider=provider,
                protocol_family="http-command",
                action=action,
                transport="HTTP",
                method=exchange.method.upper(),
                endpoint_template=endpoint,
                request_format=template_value(
                    exchange.request_body,
                    request_side=True,
                    sensitive_keys=sensitive_keys,
                    dynamic_keys=dynamic_keys,
                ),
                response_format=template_value(
                    exchange.response_body,
                    request_side=False,
                ),
                dynamic_fields=[
                    f"$.{name}"
                    for name in sorted(dynamic_keys)
                ],
                sensitive_fields=[
                    f"$.{name}"
                    for name in sorted(sensitive_keys)
                ],
                evidence=[source_ref, exchange.evidence_id],
                demo_state=demo_state,
                live_state=live_state,
                notes=list(notes),
            )
        )
    return records
