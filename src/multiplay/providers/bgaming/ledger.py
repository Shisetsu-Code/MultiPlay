from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlsplit

from ...endpoints import (
    classify_payload_fields,
    records_from_analysis,
    sanitize_endpoint_url,
    template_payload,
)
from ...models import AnalysisResult, EndpointRecord, EvidenceBundle, ValidationState
from .bootstrap import sanitize_session_url
from .classify import (
    API_V2,
    HYPERHIVE_JSONRPC,
    LEGACY_LINES,
    SWITCHABLE_CONTAINER,
    classify_bgaming,
)
from .wire import is_api_v2_command, is_bgaming_host, is_legacy_init


def build_bgaming_endpoint_records(
    *,
    evidence: EvidenceBundle,
    analysis: AnalysisResult,
    source_ref: str,
    environment: str,
) -> list[EndpointRecord]:
    records = records_from_analysis(
        provider="bgaming",
        analysis=analysis,
        evidence=evidence,
        source_ref=source_ref,
        environment=environment,
    )
    by_id = {item.evidence_id: item for item in evidence.http}
    families = {item.family for item in classify_bgaming(evidence)}

    normalized: list[EndpointRecord] = []
    for record in records:
        if not _provider_endpoint(record.endpoint_template):
            continue

        sample = next(
            (by_id[item] for item in record.evidence if item in by_id),
            None,
        )
        family = _record_family(sample, record.protocol_family, families)
        if not family:
            continue

        record.notes.append(f"provider_family={family}")
        record.notes.extend(_replay_notes(family))
        record.endpoint_template = sanitize_session_url(record.endpoint_template)

        if sample is not None and isinstance(sample.request_body, dict):
            command = sample.request_body.get("command")
            if isinstance(command, str) and command:
                record.action = command
            method = sample.request_body.get("method")
            if (
                sample.request_body.get("jsonrpc") == "2.0"
                and isinstance(method, str)
                and method
            ):
                record.action = f"rpc:{method}"

        if family == HYPERHIVE_JSONRPC:
            _normalize_hyperhive_record(record, sample)
        if family == LEGACY_LINES and record.action == "spin":
            _normalize_legacy_spin_record(record)
        record.notes = list(dict.fromkeys(record.notes))
        normalized.append(record)

    records = normalized
    records.extend(
        _hyperhive_variant_records(
            evidence=evidence,
            source_ref=source_ref,
            environment=environment,
        )
    )
    records.extend(
        _switch_records(
            evidence=evidence,
            source_ref=source_ref,
            environment=environment,
        )
    )
    return records


def _record_family(
    sample,
    protocol_family: str,
    families: set[str],
) -> str:
    if protocol_family == "jsonrpc-2.0":
        return HYPERHIVE_JSONRPC
    if sample is not None:
        if is_legacy_init(sample.response_body):
            return LEGACY_LINES
        if is_api_v2_command(sample.request_body):
            options = (
                sample.request_body.get("options")
                if isinstance(sample.request_body, dict)
                else None
            )
            if LEGACY_LINES in families and isinstance(options, dict) and "bets" in options:
                return LEGACY_LINES
            return API_V2
    return ""


def _provider_endpoint(url: str) -> bool:
    host = (urlsplit(str(url or "")).hostname or "").casefold()
    return is_bgaming_host(host)


def _replay_notes(family: str) -> list[str]:
    if family == HYPERHIVE_JSONRPC:
        return [
            "live_replay=fresh token/state_lock only; never replay captured credentials",
            "live_replay=preserve req.bet scalar type, state_lock presence, custom_req and params extras",
            "live_replay=preserve current-client RPC id policy",
        ]
    if family == LEGACY_LINES:
        return [
            "live_replay=refresh session/CSRF",
            "live_replay=re-read current line count and preserve complete options.lines mapping",
        ]
    if family == API_V2:
        return [
            "live_replay=refresh session/CSRF and round_series_id",
            "live_replay=preserve demonstrated command/options/extra_data shape",
        ]
    if family == SWITCHABLE_CONTAINER:
        return [
            "live_replay=resolve child variant through current lobby endpoint",
            "live_replay=use fresh identifier/api/CSRF returned by switch",
        ]
    return []



_HYPERHIVE_DYNAMIC_KEYS = {
    "action_id",
    "bet",
    "exponent",
    "id",
    "nonce",
    "round_id",
    "stake",
    "state_lock",
    "timestamp",
}
_HYPERHIVE_SENSITIVE_MARKERS = {
    "authorization",
    "cookie",
    "csrf",
    "password",
    "secret",
    "session",
    "token",
}


def _normalize_hyperhive_record(record: EndpointRecord, sample) -> None:
    if sample is None or not isinstance(sample.request_body, dict):
        return
    payload = sample.request_body
    if payload.get("jsonrpc") != "2.0":
        return

    dynamic: list[str] = []
    sensitive: list[str] = []
    record.request_format = _hyperhive_value(
        payload,
        path="$",
        dynamic=dynamic,
        sensitive=sensitive,
    )
    record.dynamic_fields = sorted(set(dynamic))
    record.sensitive_fields = sorted(set(sensitive))


def _hyperhive_value(
    value,
    *,
    path: str,
    dynamic: list[str],
    sensitive: list[str],
):
    if isinstance(value, dict):
        out = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            lowered = key.casefold()

            if any(marker in lowered for marker in _HYPERHIVE_SENSITIVE_MARKERS):
                out[key] = "<redacted>"
                sensitive.append(child_path)
                continue

            if lowered in _HYPERHIVE_DYNAMIC_KEYS:
                out[key] = f"<dynamic:{key}>"
                dynamic.append(child_path)
                continue

            out[key] = _hyperhive_value(
                child,
                path=child_path,
                dynamic=dynamic,
                sensitive=sensitive,
            )
        return out

    if isinstance(value, list):
        return [
            _hyperhive_value(
                child,
                path=f"{path}[]",
                dynamic=dynamic,
                sensitive=sensitive,
            )
            for child in value
        ]
    return value


def _normalize_legacy_spin_record(record: EndpointRecord) -> None:
    request = record.request_format
    if not isinstance(request, dict):
        return
    options = request.get("options")
    if isinstance(options, dict):
        bets = options.get("bets")
        if isinstance(bets, dict):
            options["bets"] = {
                str(key): "<dynamic:line_bet>"
                for key in bets
            }
            if "$.options.bets" not in record.dynamic_fields:
                record.dynamic_fields.append("$.options.bets")
    extra = request.get("extra_data")
    if isinstance(extra, dict) and "client_seed" in extra:
        extra["client_seed"] = "<dynamic:client_seed>"
        if "$.extra_data.client_seed" not in record.dynamic_fields:
            record.dynamic_fields.append("$.extra_data.client_seed")
    record.dynamic_fields.sort()



def _hyperhive_variant_records(
    *,
    evidence: EvidenceBundle,
    source_ref: str,
    environment: str,
) -> list[EndpointRecord]:
    merged: dict[tuple[str, str], EndpointRecord] = {}

    for exchange in evidence.http:
        body = exchange.request_body
        if (
            exchange.response_status is None
            or not 200 <= exchange.response_status < 400
            or not isinstance(body, dict)
            or body.get("jsonrpc") != "2.0"
            or body.get("method") != "play"
        ):
            continue

        params = body.get("params")
        req = params.get("req") if isinstance(params, dict) else None
        if not isinstance(req, dict):
            continue

        discriminator = _hyperhive_discriminator(req)
        canonical = json.dumps(
            discriminator,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        variant = (
            "base"
            if not discriminator
            else "variant-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        )

        dynamic: list[str] = []
        sensitive: list[str] = []
        request_format = _hyperhive_value(
            body,
            path="$",
            dynamic=dynamic,
            sensitive=sensitive,
        )
        action = f"rpc:play:{variant}"
        endpoint = sanitize_session_url(exchange.url)
        key = (endpoint, action)

        existing = merged.get(key)
        if existing is not None:
            if exchange.evidence_id not in existing.evidence:
                existing.evidence.append(exchange.evidence_id)
            continue

        notes = [
            *_replay_notes(HYPERHIVE_JSONRPC),
            f"variant={variant}",
        ]
        if discriminator:
            notes.append(f"variant_discriminator={canonical}")

        merged[key] = EndpointRecord(
            provider="bgaming",
            protocol_family=HYPERHIVE_JSONRPC,
            action=action,
            transport="HTTP",
            method="POST",
            endpoint_template=endpoint,
            request_format=request_format,
            response_format=template_payload(
                exchange.response_body,
                request_side=False,
            ),
            dynamic_fields=sorted(set(dynamic)),
            sensitive_fields=sorted(set(sensitive)),
            evidence=[source_ref, exchange.evidence_id],
            demo_state=ValidationState.OBSERVED,
            live_state=(
                ValidationState.OBSERVED
                if environment == "live"
                else ValidationState.UNKNOWN
            ),
            notes=notes,
        )

    return list(merged.values())


def _hyperhive_discriminator(req: dict) -> dict:
    out = {}
    for raw_key, value in req.items():
        key = str(raw_key)
        lowered = key.casefold()
        if lowered in {"bet", "bet_type"}:
            continue
        if lowered in _HYPERHIVE_DYNAMIC_KEYS:
            continue
        if any(marker in lowered for marker in _HYPERHIVE_SENSITIVE_MARKERS):
            continue

        cleaned = _hyperhive_discriminator_value(value)
        if cleaned not in ({}, [], None):
            out[key] = cleaned
    return out


def _hyperhive_discriminator_value(value):
    if isinstance(value, dict):
        out = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            lowered = key.casefold()
            if lowered in _HYPERHIVE_DYNAMIC_KEYS:
                continue
            if any(marker in lowered for marker in _HYPERHIVE_SENSITIVE_MARKERS):
                continue
            cleaned = _hyperhive_discriminator_value(child)
            if cleaned not in ({}, [], None):
                out[key] = cleaned
        return out
    if isinstance(value, list):
        return [
            cleaned
            for child in value
            if (cleaned := _hyperhive_discriminator_value(child)) not in ({}, [], None)
        ]
    return value


def _switch_records(
    *,
    evidence: EvidenceBundle,
    source_ref: str,
    environment: str,
) -> list[EndpointRecord]:
    records: list[EndpointRecord] = []
    for exchange in evidence.http:
        if exchange.method != "GET" or not _switch_response(exchange.response_body):
            continue
        parts = urlsplit(exchange.url)
        query = parse_qs(parts.query, keep_blank_values=True)
        if not {"game", "from"}.intersection(query):
            continue

        request_format = {
            "query": {
                key: f"<dynamic:{key}>"
                for key in sorted(query)
            }
        }
        _dynamic, sensitive = classify_payload_fields(request_format)
        records.append(
            EndpointRecord(
                provider="bgaming",
                protocol_family=SWITCHABLE_CONTAINER,
                action="switch_variant",
                transport="HTTP",
                method="GET",
                endpoint_template=sanitize_endpoint_url(exchange.url),
                request_format=request_format,
                response_format=template_payload(
                    exchange.response_body,
                    request_side=False,
                ),
                dynamic_fields=["$.query.from", "$.query.game"],
                sensitive_fields=sensitive,
                evidence=[source_ref, exchange.evidence_id],
                demo_state=ValidationState.OBSERVED,
                live_state=(
                    ValidationState.OBSERVED
                    if environment == "live"
                    else ValidationState.UNKNOWN
                ),
                notes=_replay_notes(SWITCHABLE_CONTAINER),
            )
        )
    return records


def _switch_response(value) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("identifier"), str)
        and bool(value.get("api"))
        and bool(value.get("csrfTokenHeaderName"))
    )
