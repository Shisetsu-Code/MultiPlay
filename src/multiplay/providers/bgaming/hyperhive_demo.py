from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from ...models import EvidenceBundle, HttpExchange, ScriptEvidence
from .bootstrap import extract_window_options, sanitize_bootstrap_options
from .hyperhive_client import collect_hyperhive_contract_scripts
from .hyperhive_wire_profile import (
    HyperHiveWireProfile,
    analyze_current_wire,
    build_profile_request,
)
from .probe import _allowed_source, _HttpSession, _is_hyperhive_url, _resolve_demo


@dataclass(frozen=True, slots=True)
class HyperHiveDemoMetadata:
    requested_url: str
    launch_url: str
    inner_url: str
    default_bet: int | float
    init_status: int
    play_status: int
    play_success: bool
    profile: HyperHiveWireProfile

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requested_url"] = _strip_query(self.requested_url)
        data["launch_url"] = _strip_query(self.launch_url)
        data["inner_url"] = _strip_query(self.inner_url)
        data["profile"] = self.profile.to_dict()
        return data


@dataclass(frozen=True, slots=True)
class HyperHiveDemoResult:
    evidence: EvidenceBundle
    metadata: HyperHiveDemoMetadata


def run_demo_hyperhive(
    url: str,
    *,
    timeout_s: float = 30.0,
) -> HyperHiveDemoResult:
    source = str(url or "").strip()
    if not source:
        raise ValueError("BGaming HyperHive URL is empty.")
    if not _allowed_source(source):
        raise ValueError("BGaming HyperHive accepts only BGaming URLs.")

    session = _HttpSession()
    outer = _resolve_demo(session, source, timeout_s=timeout_s)
    if not _is_hyperhive_url(outer.url):
        raise ValueError("Resolved BGaming runtime is not HyperHive.")

    options = extract_window_options(outer.text)
    token = str(options.get("play_token") or "").strip()
    if not token:
        raise ValueError("BGaming HyperHive bootstrap has no play_token.")

    origin = _origin(outer.url)
    inner_url = origin + "/?token=" + quote(token, safe="")
    inner = session.get(
        inner_url,
        timeout_s=timeout_s,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": outer.url,
        },
    )

    scripts = collect_hyperhive_contract_scripts(
        session,
        inner_html=inner.text,
        inner_url=inner.url,
        outer_url=outer.url,
        timeout_s=timeout_s,
    )
    contract = "\n".join(text for _url, text in scripts)
    profile = analyze_current_wire(contract, script_count=len(scripts))

    rpc_url = origin + "/api"
    rpc_headers = {
        "Origin": origin,
        "Referer": inner.url,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    init_payload = {
        "id": _rpc_id(profile),
        "jsonrpc": "2.0",
        "method": "init",
        "params": {"token": token},
    }
    init = session.post_json(
        rpc_url,
        init_payload,
        timeout_s=timeout_s,
        headers=rpc_headers,
        allow_http_error=True,
    )
    init_data = _json_object(init.text, "init")
    _require_rpc_success(init_data, "init", init.status)

    init_result = init_data.get("result")
    if not isinstance(init_result, dict):
        raise TypeError("BGaming HyperHive init result is not an object.")

    default_bet = resolve_hyperhive_bet(init_result)
    state_lock = init_result.get("state_lock")
    exponent = _currency_exponent(init_result)

    request = build_profile_request(
        profile,
        init_result,
        bet=default_bet,
    )
    if profile.req_action and not profile.custom_req:
        request["action"] = "spin"

    if profile.custom_req:
        custom = dict(profile.custom_literals)
        if profile.custom_action:
            custom["action"] = "spin"
        if profile.custom_exponent:
            custom["exponent"] = exponent
        if profile.custom_stake:
            custom["stake"] = default_bet
        if custom:
            request["custom_req"] = custom

    play_params: dict[str, Any] = {
        "token": token,
        "req": request,
    }
    if profile.state_lock_present:
        play_params["state_lock"] = "" if state_lock is None else state_lock

    play_payload = {
        "id": _rpc_id(profile),
        "jsonrpc": "2.0",
        "method": "play",
        "params": play_params,
    }
    play = session.post_json(
        rpc_url,
        play_payload,
        timeout_s=timeout_s,
        headers=rpc_headers,
        allow_http_error=True,
    )
    play_data = _json_object(play.text, "play")
    play_success = (
        200 <= play.status < 400
        and play_data.get("error") in (None, {}, [])
    )

    http_evidence = [
        HttpExchange(
            evidence_id="hyperhive:init",
            method="POST",
            url=rpc_url,
            request_headers={"content-type": "application/json"},
            request_body=_safe_rpc(init_payload),
            response_status=init.status,
            response_body=_safe_rpc(init_data),
        ),
    ]
    if play_success:
        http_evidence.append(
            HttpExchange(
                evidence_id="hyperhive:play",
                method="POST",
                url=rpc_url,
                request_headers={"content-type": "application/json"},
                request_body=_safe_rpc(play_payload),
                response_status=play.status,
                response_body=_safe_rpc(play_data),
            )
        )

    evidence = EvidenceBundle(
        http=http_evidence,
        scripts=[
            ScriptEvidence(
                evidence_id=f"hyperhive:script:{index}",
                source=_strip_query(script_url),
                text=script_text,
            )
            for index, (script_url, script_text) in enumerate(scripts)
        ],
        metadata={
            "source": "bgaming-hyperhive-demo",
            "bootstrap": sanitize_bootstrap_options(options),
            "play_attempt": {
                "status": play.status,
                "success": play_success,
                "error": _safe_rpc(play_data.get("error")),
            },
        },
    )
    return HyperHiveDemoResult(
        evidence=evidence,
        metadata=HyperHiveDemoMetadata(
            requested_url=source,
            launch_url=outer.url,
            inner_url=inner.url,
            default_bet=default_bet,
            init_status=init.status,
            play_status=play.status,
            play_success=play_success,
            profile=profile,
        ),
    )


def resolve_hyperhive_bet(init_result: dict[str, Any]) -> int | float:
    config = init_result.get("config")
    if not isinstance(config, dict):
        raise TypeError("BGaming HyperHive init has no config object.")

    default = config.get("default_bet")
    if _positive_number(default):
        return default

    limits = config.get("bet_limits")
    if isinstance(limits, list):
        numeric = [item for item in limits if _positive_number(item)]
        if numeric:
            return min(numeric)
    raise ValueError("BGaming HyperHive init exposes no usable bet.")


def _currency_exponent(init_result: dict[str, Any]) -> int:
    attrs = init_result.get("currency_attributes")
    if isinstance(attrs, dict):
        value = attrs.get("exponent")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 2


def _require_rpc_success(
    payload: dict[str, Any],
    phase: str,
    status: int,
) -> None:
    if not 200 <= status < 400:
        raise RuntimeError(f"BGaming HyperHive {phase} HTTP {status}.")
    if payload.get("error") not in (None, {}, []):
        raise RuntimeError(
            f"BGaming HyperHive {phase} RPC error: {payload.get('error')!r}"
        )


def _json_object(text: str, phase: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"BGaming HyperHive {phase} response is not JSON."
        ) from exc
    if not isinstance(value, dict):
        raise TypeError(f"BGaming HyperHive {phase} response is not an object.")
    return value


def _safe_rpc(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).casefold()
            if "token" in lowered or lowered == "state_lock":
                out[str(key)] = "<redacted>"
            else:
                out[str(key)] = _safe_rpc(child)
        return out
    if isinstance(value, list):
        return [_safe_rpc(item) for item in value]
    return value


def _rpc_id(profile: HyperHiveWireProfile) -> int | str:
    return 0 if profile.rpc_id_zero else str(uuid.uuid4())


def _positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    )


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _strip_query(url: str) -> str:
    parsed = urlsplit(url)
    return parsed._replace(query="", fragment="").geturl()
