from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from ...evidence import redact
from ...models import EvidenceBundle, HttpExchange, ScriptEvidence
from .bootstrap import (
    extract_bootstrap_options,
    sanitize_bootstrap_options,
    sanitize_session_url,
)
from .classify import API_V2, LEGACY_LINES
from .probe import _allowed_source, _HttpSession, _is_hyperhive_url, _resolve_demo
from .wire import is_legacy_init, is_switchable_init


@dataclass(frozen=True, slots=True)
class DemoBaseSpinMetadata:
    requested_url: str
    launch_url: str
    identifier: str
    family: str
    wager: float
    line_count: int
    init_status: int
    spin_status: int

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["launch_url"] = sanitize_session_url(self.launch_url)
        data["requested_url"] = _safe_source(self.requested_url)
        return data


@dataclass(frozen=True, slots=True)
class DemoBaseSpinResult:
    evidence: EvidenceBundle
    metadata: DemoBaseSpinMetadata


def run_demo_base_spin(
    url: str,
    *,
    timeout_s: float = 30.0,
) -> DemoBaseSpinResult:
    source = str(url or "").strip()
    if not source:
        raise ValueError("BGaming demo spin URL is empty.")
    if not _allowed_source(source):
        raise ValueError("BGaming demo spin accepts only BGaming URLs.")

    session = _HttpSession()
    launch = _resolve_demo(session, source, timeout_s=timeout_s)
    if _is_hyperhive_url(launch.url):
        raise ValueError("HyperHive requires its JSON-RPC demo executor.")

    bootstrap = extract_bootstrap_options(launch.text)
    round_series_id = int(time.time() * 1000)
    common_headers = _game_headers(
        bootstrap.api,
        launch.url,
        bootstrap.csrf_header_name,
        bootstrap.csrf_header_value,
    )

    init_payload = {
        "command": "init",
        "extra_data": {"round_series_id": round_series_id},
    }
    init = session.post_json(
        bootstrap.api,
        init_payload,
        timeout_s=timeout_s,
        headers=common_headers,
    )
    init_data = _json_object(init.text, "init")
    api_version_required = False

    # Some current API-v2 games require api_version=2 even on init.
    # Retry once only when the first response does not expose a usable game contract.
    if not is_legacy_init(init_data) and not is_switchable_init(init_data):
        options = init_data.get("options")
        if not isinstance(options, dict):
            retry_payload = {
                "command": "init",
                "extra_data": {
                    "round_series_id": round_series_id,
                    "api_version": 2,
                },
            }
            retry = session.post_json(
                bootstrap.api,
                retry_payload,
                timeout_s=timeout_s,
                headers=common_headers,
                allow_http_error=True,
            )
            retry_data = _json_object(retry.text, "init")
            if isinstance(retry_data.get("options"), dict):
                init_payload = retry_payload
                init = retry
                init_data = retry_data
                api_version_required = True

    if is_switchable_init(init_data):
        raise ValueError("Switchable container requires variant selection before spin.")

    if is_legacy_init(init_data):
        family = LEGACY_LINES
        wager, line_count, spin_options = legacy_spin_options(init_data)
        spin_extra = {
            "client_seed": secrets.randbelow(100000),
            "round_series_id": round_series_id,
        }
    else:
        family = API_V2
        wager = float(resolve_base_bet(init_data))
        line_count = 0
        spin_options = {"bet": _preserve_numeric_type(init_data, wager)}
        spin_extra = {"round_series_id": round_series_id}
        if api_version_required:
            spin_extra["api_version"] = 2

    spin_payload = {
        "command": "spin",
        "options": spin_options,
        "extra_data": spin_extra,
    }
    spin = session.post_json(
        bootstrap.api,
        spin_payload,
        timeout_s=timeout_s,
        headers=common_headers,
        allow_http_error=True,
    )
    spin_data = _json_value(spin.text)

    # Some API-v2 clients serialize the active math variant as options.mode.
    # Retry only after a failed base spin so successful simple games stay untouched.
    if (
        family == API_V2
        and not 200 <= spin.status < 400
        and "mode" not in spin_options
    ):
        retry_options = dict(spin_options)
        retry_options["mode"] = "0"
        retry_payload = {
            "command": "spin",
            "options": retry_options,
            "extra_data": dict(spin_extra),
        }
        retry_spin = session.post_json(
            bootstrap.api,
            retry_payload,
            timeout_s=timeout_s,
            headers=common_headers,
            allow_http_error=True,
        )
        retry_data = _json_value(retry_spin.text)
        if 200 <= retry_spin.status < 400:
            spin_payload = retry_payload
            spin = retry_spin
            spin_data = retry_data

    safe_api = sanitize_session_url(bootstrap.api)
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="demo:init",
                method="POST",
                url=safe_api,
                request_headers={
                    "content-type": "application/json",
                    bootstrap.csrf_header_name.casefold(): "<redacted>",
                },
                request_body=init_payload,
                response_status=init.status,
                response_body=redact(init_data),
            ),
            HttpExchange(
                evidence_id="demo:spin",
                method="POST",
                url=safe_api,
                request_headers={
                    "content-type": "application/json",
                    bootstrap.csrf_header_name.casefold(): "<redacted>",
                },
                request_body=spin_payload,
                response_status=spin.status,
                response_body=redact(spin_data),
            ),
        ],
        scripts=[
            ScriptEvidence(
                evidence_id="demo:bootstrap",
                source=sanitize_session_url(launch.url),
                text=json.dumps(
                    sanitize_bootstrap_options(bootstrap.raw),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        ],
        metadata={"source": "bgaming-demo-base-spin"},
    )
    return DemoBaseSpinResult(
        evidence=evidence,
        metadata=DemoBaseSpinMetadata(
            requested_url=source,
            launch_url=launch.url,
            identifier=bootstrap.identifier,
            family=family,
            wager=wager,
            line_count=line_count,
            init_status=init.status,
            spin_status=spin.status,
        ),
    )


def resolve_base_bet(init_data: dict[str, Any]) -> int | float:
    options = init_data.get("options")
    if not isinstance(options, dict):
        raise TypeError("BGaming init has no options object.")

    default = options.get("default_bet")
    if _positive_number(default):
        return default

    available = options.get("available_bets")
    if isinstance(available, list):
        numeric = [item for item in available if _positive_number(item)]
        if numeric:
            return min(numeric)

    bet = options.get("bet")
    if _positive_number(bet):
        return bet
    raise ValueError("BGaming init exposes no usable base bet.")


def legacy_spin_options(
    init_data: dict[str, Any],
) -> tuple[float, int, dict[str, dict[str, int | float]]]:
    options = init_data.get("options")
    if not isinstance(options, dict):
        raise TypeError("BGaming legacy init has no options object.")
    line_bets = options.get("line_bets")
    lines = options.get("lines")
    if not isinstance(line_bets, list) or not isinstance(lines, list) or not lines:
        raise ValueError("BGaming legacy init has no line_bets/lines contract.")

    numeric = [item for item in line_bets if _positive_number(item)]
    if not numeric:
        raise ValueError("BGaming legacy init exposes no positive line bet.")
    wager = min(numeric)
    line_count = len(lines)
    bets = {str(index): wager for index in range(line_count)}
    return float(wager), line_count, {"bets": bets}


def _game_headers(
    api_url: str,
    launch_url: str,
    csrf_name: str,
    csrf_value: str,
) -> dict[str, str]:
    parsed = urlsplit(api_url)
    return {
        "Origin": f"{parsed.scheme}://{parsed.netloc}",
        "Referer": launch_url,
        csrf_name: csrf_value,
    }


def _json_object(text: str, phase: str) -> dict[str, Any]:
    value = _json_value(text)
    if not isinstance(value, dict):
        raise TypeError(f"BGaming {phase} response is not a JSON object.")
    return value


def _json_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_non_json_text": str(text or "")[:4000]}


def _positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    )


def _preserve_numeric_type(init_data: dict[str, Any], wager: float) -> int | float:
    options = init_data.get("options")
    if isinstance(options, dict):
        default = options.get("default_bet")
        if _positive_number(default) and float(default) == wager:
            return default
        available = options.get("available_bets")
        if isinstance(available, list):
            for item in available:
                if _positive_number(item) and float(item) == wager:
                    return item
    return wager


def _api_version(init_data: dict[str, Any]) -> int | str | None:
    value = init_data.get("api_version")
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        return text or None
    return None


def _safe_source(url: str) -> str:
    parsed = urlsplit(url)
    return parsed._replace(query="", fragment="").geturl()
