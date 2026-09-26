from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HyperHiveWireProfile:
    rpc_id_zero: bool
    bet_type: str
    req_action: bool
    state_lock_present: bool
    custom_req: bool
    custom_action: bool
    custom_exponent: bool
    custom_stake: bool
    custom_literals: dict[str, Any]
    script_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_current_wire(
    text: str,
    *,
    script_count: int = 0,
) -> HyperHiveWireProfile:
    compact = re.sub(r"\s+", "", text or "")
    scoped = _request_literals(compact, "bet_type")
    loose = _literal_values(compact, "bet_type")
    normal = {value.casefold() for value in scoped if value.casefold() != "freebet"}
    loose_normal = {
        value.casefold()
        for value in loose
        if value.casefold() != "freebet"
    }

    if "betting" in normal:
        bet_type = "betting"
    elif "bet" in normal:
        bet_type = "bet"
    elif len(normal) == 1:
        bet_type = next(iter(normal))
    elif "betting" in loose_normal:
        bet_type = "betting"
    elif "bet" in loose_normal:
        bet_type = "bet"
    elif len(loose_normal) == 1:
        bet_type = next(iter(loose_normal))
    else:
        bet_type = ""

    custom_req = bool(
        re.search(
            r"\.req\.custom_req=[^;]{0,240}formattedRequest\.params",
            compact,
        )
    )
    literals = _formatted_request_literals(compact) if custom_req else {}

    return HyperHiveWireProfile(
        rpc_id_zero=bool(
            re.search(
                r'(?:\bid:0,jsonrpc|["\']id["\']:0|\.id=0)',
                compact,
            )
        ),
        bet_type=bet_type,
        req_action=bool(_request_literals(compact, "action")),
        state_lock_present=_play_has_state_lock(compact),
        custom_req=custom_req,
        custom_action=custom_req and "formattedRequest.params.action" in compact,
        custom_exponent=custom_req and "formattedRequest.params.exponent" in compact,
        custom_stake=custom_req and "formattedRequest.params.stake" in compact,
        custom_literals=literals,
        script_count=max(0, int(script_count)),
    )


def _request_literals(text: str, key: str) -> set[str]:
    escaped = re.escape(key)
    values: set[str] = set()
    for pattern in (
        rf'\breq:\{{[^{{}}]{{0,1600}}\b{escaped}:["\']([^"\']{{1,80}})["\']',
        rf'\.req\.{escaped}=["\']([^"\']{{1,80}})["\']',
        rf'\.req\[["\']{escaped}["\']\]=["\']([^"\']{{1,80}})["\']',
    ):
        values.update(re.findall(pattern, text or ""))
    return values


def _literal_values(text: str, key: str) -> set[str]:
    escaped = re.escape(key)
    values: set[str] = set()
    for pattern in (
        rf'\b{escaped}:["\']([^"\']{{1,80}})["\']',
        rf'\.{escaped}=["\']([^"\']{{1,80}})["\']',
    ):
        values.update(re.findall(pattern, text or ""))
    return values


def _play_has_state_lock(text: str) -> bool:
    if not re.search(
        r'(?:method|["\']method["\']):["\']play["\']',
        text or "",
    ):
        return False
    return bool(
        re.search(r'(?:\bstate_lock\b|["\']state_lock["\']):', text or "")
        or re.search(r'\.params\.state_lock=', text or "")
    )


def _formatted_request_literals(text: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    scalar = (
        r'(?:!0|!1|true|false|null|-?\d+(?:\.\d+)?|'
        r'"[^"\\]{0,200}"|\'[^\'\\]{0,200}\')'
    )
    for match in re.finditer(
        rf"formattedRequest\.params\.([A-Za-z_$][A-Za-z0-9_$]*)=({scalar})",
        text or "",
    ):
        key = match.group(1)
        if not _safe_literal_key(key):
            continue
        try:
            found[key] = _parse_scalar(match.group(2))
        except ValueError:
            continue

    for dynamic in ("action", "exponent", "stake"):
        found.pop(dynamic, None)
    return found


def _safe_literal_key(key: str) -> bool:
    lowered = str(key or "").casefold()
    return bool(
        re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", str(key or ""))
        and not any(
            marker in lowered
            for marker in (
                "token",
                "secret",
                "password",
                "session",
                "csrf",
                "nonce",
                "seed",
            )
        )
    )


def _parse_scalar(raw: str) -> Any:
    value = str(raw or "").strip()
    if value in {"true", "!0"}:
        return True
    if value in {"false", "!1"}:
        return False
    if value == "null":
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+)", value):
        return float(value)
    raise ValueError("not a safe scalar")
