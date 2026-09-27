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
    req_purchased_feature: bool = False
    req_purchased_feature_always: bool = False
    req_purchased_feature_omit_empty: bool = False
    req_balance: bool = False
    req_fe_exponent: bool = False
    req_buy_bonus_multiplier: bool = False
    base_buy_bonus_multiplier: int | float | None = None
    buy_bonus_multiplier: int | float | None = None
    req_model_rev: int | float | None = None
    req_min_exponent: bool = False
    req_integration_id: bool = False

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
    play_window = _play_request_window(compact)

    if not bet_type and play_window:
        bet_type = _normal_bet_type_from_play_window(play_window)

    base_multiplier, purchase_multiplier = _buy_bonus_multipliers(
        compact,
        play_window,
    )

    return HyperHiveWireProfile(
        rpc_id_zero=bool(
            re.search(
                r'(?:\bid:0,jsonrpc|["\']id["\']:0|\.id=0)',
                compact,
            )
        ),
        bet_type=bet_type,
        req_action=_play_req_action_present(compact),
        state_lock_present=_play_has_state_lock(compact),
        custom_req=custom_req,
        custom_action=custom_req and "formattedRequest.params.action" in compact,
        custom_exponent=custom_req and "formattedRequest.params.exponent" in compact,
        custom_stake=custom_req and "formattedRequest.params.stake" in compact,
        custom_literals=literals,
        script_count=max(0, int(script_count)),
        req_purchased_feature=_req_field_present(play_window, "purchased_feature"),
        req_purchased_feature_always=(
            _req_literal_field_present(
                play_window,
                "purchased_feature",
            )
            and not _req_field_is_conditional_spread(
                play_window,
                "purchased_feature",
            )
        ),
        req_purchased_feature_omit_empty=(
            _req_field_uses_void_zero(
                play_window,
                "purchased_feature",
            )
            or _req_field_is_conditional_spread(
                play_window,
                "purchased_feature",
            )
        ),
        req_balance=_req_field_present(play_window, "balance"),
        req_fe_exponent=_req_field_present(play_window, "fe_exponent"),
        req_buy_bonus_multiplier=_req_field_present(
            play_window,
            "buyBonusModeMultiplier",
        ),
        base_buy_bonus_multiplier=base_multiplier,
        buy_bonus_multiplier=purchase_multiplier,
        req_model_rev=_req_numeric_literal(play_window, "modelRev"),
        req_min_exponent=_req_field_present(play_window, "minExponent"),
        req_integration_id=_req_field_present(play_window, "integrationId"),
    )


def build_profile_request(
    profile: HyperHiveWireProfile,
    init_result: dict[str, Any],
    *,
    bet: float,
    purchased_feature: str | None = None,
) -> dict[str, Any]:
    """Build the client-demonstrated flat HyperHive req shape."""
    request: dict[str, Any] = {"bet": bet}
    if profile.bet_type:
        request["bet_type"] = profile.bet_type
    if profile.req_fe_exponent:
        request["fe_exponent"] = resolve_hyperhive_fe_exponent(init_result)
    if profile.req_purchased_feature and (
        purchased_feature is not None
        or (
            profile.req_purchased_feature_always
            and not profile.req_purchased_feature_omit_empty
        )
    ):
        request["purchased_feature"] = purchased_feature
    if profile.req_balance:
        balance = init_result.get("balance")
        if isinstance(balance, (int, float)) and not isinstance(balance, bool):
            request["balance"] = balance
    if profile.req_model_rev is not None:
        request["modelRev"] = profile.req_model_rev
    if profile.req_min_exponent:
        request["minExponent"] = resolve_hyperhive_fe_exponent(init_result)
    if profile.req_buy_bonus_multiplier:
        multiplier = (
            profile.buy_bonus_multiplier
            if purchased_feature
            else profile.base_buy_bonus_multiplier
        )
        if multiplier is not None:
            request["buyBonusModeMultiplier"] = multiplier

    if profile.custom_req:
        custom: dict[str, Any] = dict(profile.custom_literals)
        if profile.custom_action:
            custom["action"] = "spin"
        if profile.custom_exponent:
            custom["exponent"] = resolve_hyperhive_fe_exponent(init_result)
        if profile.custom_stake:
            custom["stake"] = bet
        request["custom_req"] = custom
    return request


def resolve_hyperhive_fe_exponent(init_result: dict[str, Any]) -> int:
    attrs = init_result.get("currency_attributes")
    config = init_result.get("config")
    exponent = 2
    subunits: int | float = 100
    if isinstance(attrs, dict):
        raw_exponent = attrs.get("exponent")
        raw_subunits = attrs.get("subunits")
        if isinstance(raw_exponent, int) and not isinstance(raw_exponent, bool):
            exponent = max(0, raw_exponent)
        if (
            isinstance(raw_subunits, (int, float))
            and not isinstance(raw_subunits, bool)
            and raw_subunits > 0
        ):
            subunits = raw_subunits

    limits = config.get("bet_limits") if isinstance(config, dict) else None
    if not isinstance(limits, list):
        return exponent

    out = exponent
    for raw in limits:
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            continue
        value = raw / subunits
        text = format(value, ".12g")
        decimals = len(text.split(".", 1)[1]) + 1 if "." in text else 0
        out = max(out, decimals)
    return out


def _play_request_window(text: str) -> str:
    source = text or ""
    candidates: list[tuple[str, str]] = []

    # Keep method/invoke candidates tight enough that adjacent bonus/wheel
    # requests do not contaminate the normal-spin profile.
    play_matches = list(
        re.finditer(
            r'(?:\.invoke\(["\']play["\']|\bmethod\s*:\s*["\']play["\'])',
            source,
        )
    )
    for index, match in enumerate(play_matches):
        start = max(0, match.start() - 300)
        next_start = (
            play_matches[index + 1].start()
            if index + 1 < len(play_matches)
            else len(source)
        )
        end = min(len(source), match.start() + 2600, next_start)
        window = source[start:end]
        if re.search(r'\breq\s*:', window) or ".req." in window:
            candidates.append(("play", window))

    # Intercom-style clients materialize req in a variable before action().
    for match in re.finditer(
        r'\.action\(\{[^{}]{0,300}\bstate_lock\s*:',
        source,
    ):
        start = max(0, match.start() - 1600)
        end = min(len(source), match.start() + 2600)
        window = source[start:end]
        if re.search(r'\breq\s*:', window) or ".req." in window:
            candidates.append(("action", window))

    if not candidates:
        return ""

    def rank(item: tuple[str, str]) -> tuple[int, int]:
        _kind, window = item
        score = 0
        prefix = window[:900]

        if re.search(r'(?:^|[,;{])play\s*:\s*(?:async)?', prefix):
            score += 30
        if re.search(r'\baction\s*:\s*["\']spin["\']', window):
            score += 20
        if re.search(r'\bbet_type\s*:', window):
            score += 3
        if "purchased_feature" not in window:
            score += 8
        if _req_field_is_conditional_spread(window, "purchased_feature"):
            score += 12
        if "formattedRequest.params" in window:
            score += 6
        if re.search(
            r'\baction\s*:\s*["\'](?:bonus|wheel|collect)["\']',
            window,
        ):
            score -= 15

        return (score, -len(window))

    return max(candidates, key=rank)[1]

def _play_req_action_present(text: str) -> bool:
    """Detect req.action only inside a play payload, never from init."""
    source = text or ""
    candidates: list[str] = []
    for match in re.finditer(
        r'(?:\bmethod\s*:\s*["\']play["\']|\.invoke\(["\']play["\'])',
        source,
    ):
        window = source[match.start() : min(len(source), match.start() + 2800)]
        if re.search(r'\breq\s*:', window) or ".req." in window:
            candidates.append(window)
    return any(_req_field_present(window, "action") for window in candidates)


def _req_field_is_conditional_spread(window: str, key: str) -> bool:
    if not window:
        return False
    escaped = re.escape(key)
    return bool(
        re.search(
            rf'\.\.\.[^,{{}}]{{0,180}}\?\s*\{{'
            rf'[^{{}}]{{0,320}}\b{escaped}\s*:',
            window,
        )
        or re.search(
            rf'\.\.\.[^,{{}}]{{0,180}}&&\s*\{{'
            rf'[^{{}}]{{0,320}}\b{escaped}\s*:',
            window,
        )
    )


def _req_numeric_literal(window: str, key: str) -> int | float | None:
    if not window:
        return None
    escaped = re.escape(key)
    match = re.search(
        rf'\b{escaped}\s*:\s*(-?\d+(?:\.\d+)?)',
        window,
    )
    return _number_scalar(match.group(1)) if match else None


def _req_literal_field_present(window: str, key: str) -> bool:
    """Return true only when the request field has a concrete JSON scalar literal."""
    if not window:
        return False
    escaped = re.escape(key)
    scalar = (
        r'(?:["\'][^"\']{0,160}["\']|'
        r'!0|!1|true|false|null|-?\d+(?:\.\d+)?)'
    )
    return bool(
        re.search(
            rf'\b{escaped}\s*:\s*{scalar}(?=,|\}})',
            window,
        )
    )


def _req_field_uses_void_zero(window: str, key: str) -> bool:
    if not window:
        return False
    escaped = re.escape(key)
    field = re.search(
        rf'\b{escaped}\s*:\s*([A-Za-z_$][A-Za-z0-9_$]*)',
        window,
    )
    if field is None:
        return False
    variable = re.escape(field.group(1))
    prior = window[: field.start()][-2200:]
    return bool(
        re.search(
            rf'(?<![A-Za-z0-9_$]){variable}\s*=\s*void\s*0',
            prior,
        )
    )


def _req_field_present(window: str, key: str) -> bool:
    if not window:
        return False
    escaped = re.escape(key)
    return bool(
        re.search(rf'\b{escaped}\s*:', window)
        or re.search(rf'\.req\.{escaped}\s*=', window)
        or re.search(rf'\.req\[["\']{escaped}["\']\]\s*=', window)
    )


def _normal_bet_type_from_play_window(window: str) -> str:
    direct = re.search(
        r'\bbet_type\s*:\s*[^,{}?]{0,120}\?\s*["\']freebet["\']'
        r'\s*:\s*["\']([^"\']+)["\']',
        window or "",
    )
    if direct:
        return str(direct.group(1)).casefold()

    match = re.search(
        r'\bbet_type:([A-Za-z_$][A-Za-z0-9_$]*)',
        window or "",
    )
    if match is None:
        return ""
    variable = re.escape(match.group(1))
    prior = window[: match.start()][-1200:]
    ternary = re.search(
        rf'(?<![A-Za-z0-9_$])(?:let|const|var)?{variable}='
        rf'.{{0,900}}?["\']freebet["\']:["\']([^"\']+)["\']',
        prior,
    )
    if ternary:
        return str(ternary.group(1)).casefold()
    return ""


def _buy_bonus_multipliers(
    text: str,
    window: str,
) -> tuple[int | float | None, int | float | None]:
    base: int | float | None = None
    purchase: int | float | None = None

    field = re.search(
        r'\bbuyBonusModeMultiplier:([A-Za-z_$][A-Za-z0-9_$]*)',
        window or "",
    )
    if field is not None:
        variable = re.escape(field.group(1))
        prior = window[: field.start()][-1400:]
        assignments = re.findall(
            rf'(?:^|[,;]){variable}=(-?\d+(?:\.\d+)?)',
            prior,
        )
        if assignments:
            base = _number_scalar(assignments[-1])

    values = {
        _number_scalar(raw)
        for raw in re.findall(
            r'\bbuyBonusModeMultiplier=(-?\d+(?:\.\d+)?)',
            text or "",
        )
    }
    values.discard(None)
    if len(values) == 1:
        purchase = next(iter(values))
    return base, purchase


def _number_scalar(raw: str) -> int | float | None:
    value = str(raw or "").strip()
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+)", value):
        return float(value)
    return None


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
    source = text or ""
    has_play = bool(
        re.search(
            r'(?:method|["\']method["\']):["\']play["\']',
            source,
        )
        or re.search(r'\.invoke\(["\']play["\']', source)
        or re.search(
            r'\.action\(\{[^{}]{0,400}\bstate_lock\s*:[^{}]{0,400}\breq\s*:',
            source,
        )
    )
    if not has_play:
        return False
    return bool(
        re.search(r'(?:\bstate_lock\b|["\']state_lock["\'])\s*:', source)
        or re.search(r'\.params\.state_lock=', source)
    )


def _formatted_request_literals(text: str) -> dict[str, Any]:
    # The bridge copies formattedRequest.params into req.custom_req. Games
    # commonly define the normal-spin params in RequestMap first, then append
    # dynamic fields (action/exponent/stake) immediately before sending.
    # Keep the last demonstrated normal-spin map because game-specific code can
    # override the generic integration map loaded earlier.
    found: dict[str, Any] = _normal_spin_request_literals(text)
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


def _normal_spin_request_literals(text: str) -> dict[str, Any]:
    source = text or ""
    pattern = re.compile(
        r'ActionType:[A-Za-z_$][A-Za-z0-9_$]*\.SPIN'
        r'[\s\S]{0,700}?AdditionalData:\{'
        r'[\s\S]{0,500}?request:[A-Za-z_$][A-Za-z0-9_$]*\.SPIN'
        r'[\s\S]{0,500}?params:\{'
    )
    candidates: list[tuple[int, dict[str, Any]]] = []
    for match in pattern.finditer(source):
        object_start = match.end() - 1
        params_object = _balanced_js_object(
            source,
            object_start,
            max_chars=3600,
        )
        if not params_object:
            continue
        parsed = _safe_params_object(params_object[1:-1])
        if parsed:
            candidates.append((match.start(), parsed))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _balanced_js_object(
    text: str,
    start: int,
    *,
    max_chars: int,
) -> str:
    if start < 0 or start >= len(text) or text[start] != "{":
        return ""

    depth = 0
    quote = ""
    escaped = False
    end = min(len(text), start + max_chars)
    for index in range(start, end):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'", "\x60"}:
            quote = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _safe_params_object(body: str) -> dict[str, Any]:
    found: dict[str, Any] = {}

    # Some clients construct a fixed list of line indexes rather than writing
    # an array literal. This expression is still a deterministic client
    # literal: Array.from({length:N}, ((value,index) => index)).
    array_from_re = re.compile(
        r'(?:^|,)([A-Za-z_$][A-Za-z0-9_$]*):'
        r'Array\.from\(\{length:(\d+)\},'
        r'\(\(([A-Za-z_$][A-Za-z0-9_$]*),'
        r'([A-Za-z_$][A-Za-z0-9_$]*)\)=>'
        r'([A-Za-z_$][A-Za-z0-9_$]*)\)\)'
    )
    for match in array_from_re.finditer(body or ""):
        key = str(match.group(1))
        length = int(match.group(2))
        index_var = str(match.group(4))
        returned = str(match.group(5))
        if (
            _safe_literal_key(key)
            and index_var == returned
            and 0 <= length <= 200
        ):
            found[key] = list(range(length))

    value_re = re.compile(
        r'(?:^|,)([A-Za-z_$][A-Za-z0-9_$]*):'
        r'(\[[^\[\]{}]{0,1800}\]|!0|!1|true|false|null|'
        r'-?\d+(?:\.\d+)?|"[^"\\]{0,200}"|\'[^\'\\]{0,200}\')'
        r'(?=,|$)'
    )
    for match in value_re.finditer(body or ""):
        key = str(match.group(1))
        if not _safe_literal_key(key):
            continue
        raw = str(match.group(2))
        try:
            if raw.startswith("["):
                inner = raw[1:-1].strip()
                if not inner:
                    value: Any = []
                else:
                    value = [
                        _parse_scalar(item.strip())
                        for item in inner.split(",")
                        if item.strip()
                    ]
            else:
                value = _parse_scalar(raw)
        except ValueError:
            continue
        found[key] = value
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
