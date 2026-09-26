from __future__ import annotations

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
from .wire import is_api_v2_command, is_legacy_init


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

    for record in records:
        sample = next(
            (by_id[item] for item in record.evidence if item in by_id),
            None,
        )
        family = _record_family(sample, record.protocol_family, families)
        if family:
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

        record.notes = list(dict.fromkeys(record.notes))

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
            if LEGACY_LINES in families and isinstance(options, dict) and "lines" in options:
                return LEGACY_LINES
            return API_V2
    if SWITCHABLE_CONTAINER in families:
        return SWITCHABLE_CONTAINER
    return ""


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
