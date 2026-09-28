from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from ...models import EvidenceBundle


@dataclass(frozen=True, slots=True)
class HyperHiveStaticMode:
    mode_id: str
    kind: str
    feature: str
    multiplier: float | None
    request_fields: dict[str, Any] | None
    source: str
    wire_complete: bool = True
    requirements: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HyperHiveStaticProfile:
    source: str
    catalog_complete: bool
    wire_complete: bool
    base_request_fields: dict[str, Any] | None = None
    base_wire_complete: bool = False
    state_lock_required: bool = False
    modes: tuple[HyperHiveStaticMode, ...] = ()
    evidence_urls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_hyperhive_static_profile(
    evidence: EvidenceBundle,
) -> HyperHiveStaticProfile | None:
    sources: list[tuple[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for script in evidence.scripts:
        text = str(script.text or "")
        if not text:
            continue
        key = (str(script.source or ""), text)
        if key in seen:
            continue
        seen.add(key)
        sources.append((key[0], text))

    for exchange in evidence.http:
        body = exchange.response_body
        if body in (None, "", {}, []):
            continue
        if not isinstance(body, (str, dict, list)):
            continue
        encoded = (
            body
            if isinstance(body, str)
            else json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        )
        key = (str(exchange.url or ""), encoded)
        if key in seen:
            continue
        seen.add(key)
        sources.append((key[0], body))

    return discover_hyperhive_static_sources(sources)


def discover_hyperhive_static_sources(
    sources: Iterable[tuple[str, Any]],
) -> HyperHiveStaticProfile | None:
    rows: list[tuple[str, str, Any]] = []
    for url, value in sources:
        if isinstance(value, (dict, list)):
            rows.append(
                (
                    str(url or ""),
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                    value,
                )
            )
            continue
        if not isinstance(value, str):
            continue
        parsed: Any = None
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
        rows.append((str(url or ""), value, parsed))

    profiles: list[HyperHiveStaticProfile] = []
    for url, text, parsed in rows:
        for extractor in (
            _wild_cluster_profile,
            _jungle_profile,
            _red_hot_profile,
            _mystic_profile,
            _chicken_profile,
            _blazing_profile,
            _blackbeard_profile,
            _clash_profile,
            _legacy_obfuscated_rpc_profile,
            _sweet_profile,
            _zeus_profile,
        ):
            profile = extractor(text, url)
            if profile is not None:
                profiles.append(profile)

        if parsed is not None:
            for extractor in (
                _json_buy_profile,
                _bet_slots_profile,
                _buy_disabled_profile,
            ):
                profile = extractor(parsed, url)
                if profile is not None:
                    profiles.append(profile)

    if not profiles:
        return None
    profiles.sort(key=_score, reverse=True)
    return profiles[0]


def _score(profile: HyperHiveStaticProfile) -> tuple[int, int, int, int]:
    return (
        100 if profile.catalog_complete else 0,
        30 if profile.wire_complete else 0,
        10 if profile.base_wire_complete else 0,
        len(profile.modes),
    )


def _mode(
    mode_id: str,
    feature: str,
    multiplier: float | None,
    fields: dict[str, Any] | None,
    source: str,
    *,
    kind: str | None = None,
    complete: bool = True,
    requirements: Iterable[str] = (),
) -> HyperHiveStaticMode:
    return HyperHiveStaticMode(
        mode_id=mode_id,
        kind=kind or ("booster" if feature == "buy_chance" else "buy"),
        feature=feature,
        multiplier=multiplier,
        request_fields=fields,
        source=source,
        wire_complete=complete,
        requirements=tuple(requirements),
    )


def _profile(
    source: str,
    url: str,
    *,
    modes: Iterable[HyperHiveStaticMode] = (),
    base: dict[str, Any] | None = None,
    base_complete: bool = False,
    state_lock: bool = False,
    catalog_complete: bool = True,
    wire_complete: bool | None = None,
) -> HyperHiveStaticProfile:
    materialized = tuple(modes)
    if wire_complete is None:
        wire_complete = all(item.wire_complete for item in materialized)
    return HyperHiveStaticProfile(
        source=source,
        catalog_complete=catalog_complete,
        wire_complete=bool(wire_complete),
        base_request_fields=base,
        base_wire_complete=base_complete,
        state_lock_required=state_lock,
        modes=materialized,
        evidence_urls=(url,),
    )


def _blackbeard_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    if "bonus_multiplier_type" not in text or "freeSpinRandom" not in text:
        return None

    prices = re.search(
        r"const\s+[A-Za-z_$][\w$]*\s*=\s*[^,;]+,\s*"
        r"([A-Za-z_$][\w$]*)\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*\*\s*"
        r"[A-Za-z_$][\w$]*\.bet\s*,\s*([A-Za-z_$][\w$]*)\s*=\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*\*\s*[A-Za-z_$][\w$]*\.bet",
        text,
    )
    if prices is None:
        return None

    modes: list[HyperHiveStaticMode] = []
    chance = re.search(
        r"goldenBetMulti\s*:\s*([0-9]+(?:\.[0-9]+)?)",
        text,
    )
    if chance is not None:
        modes.append(
            _mode(
                "buy_chance",
                "buy_chance",
                _clean_number(float(chance.group(1))),
                {
                    "bet_type": "bet",
                    "purchased_feature": "buy_chance",
                },
                "client_static_bonus_multiplier",
            )
        )

    modes.extend(
        (
            _mode(
                "freeSpin",
                "buy_bonus",
                _clean_number(float(prices.group(2))),
                {
                    "bet_type": "bet",
                    "purchased_feature": "buy_bonus",
                    "bonus_multiplier_type": "freeSpin",
                },
                "client_static_bonus_multiplier",
            ),
            _mode(
                "freeSpinRandom",
                "buy_bonus",
                _clean_number(float(prices.group(4))),
                {
                    "bet_type": "bet",
                    "purchased_feature": "buy_bonus",
                    "bonus_multiplier_type": "freeSpinRandom",
                },
                "client_static_bonus_multiplier",
            ),
        )
    )

    return _profile(
        "client_static_bonus_multiplier",
        url,
        modes=modes,
        base={"bet_type": "bet"},
        base_complete=True,
    )


def _wild_cluster_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    if "bonus_buy" not in text or "purchaseFeature" not in text:
        return None
    if not re.search(r"purchased_feature\s*:\s*[A-Za-z_$]", text):
        return None

    pattern = re.compile(
        r'\{id:"([^"]+)",[^{}]{0,700}?price:([0-9]+(?:\.[0-9]+)?),'
        r'purchaseFeature:"([^"]+)"[^{}]{0,300}?\}'
    )
    modes: list[HyperHiveStaticMode] = []
    for match in pattern.finditer(text):
        mode_id, raw_price, feature = match.groups()
        if not feature.startswith("buy_"):
            continue
        modes.append(
            _mode(
                mode_id,
                feature,
                _clean_number(float(raw_price)),
                {
                    "purchased_feature": feature,
                    "bonus_buy": mode_id,
                },
                "client_static_bonus_buy_catalog",
            )
        )

    if len(modes) < 2:
        return None
    return _profile(
        "client_static_bonus_buy_catalog",
        url,
        modes=_dedupe(modes),
        base={},
        base_complete=True,
    )


def _jungle_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    multiplier = re.search(
        r"\bua\s*=\s*([0-9]+(?:\.[0-9]+)?)",
        text,
    )
    if multiplier is None:
        return None
    if "purchased_feature" not in text or "buy_bonus" not in text:
        return None
    if "buybonus" not in text:
        return None

    value = _clean_number(float(multiplier.group(1)))
    return _profile(
        "client_static_jungle_buy",
        url,
        base={"action": "spin", "bet_type": "bet"},
        base_complete=True,
        modes=(
            _mode(
                "buybonus",
                "buy_bonus",
                value,
                {
                    "action": "buybonus",
                    "id": "buybonus",
                    "purchased_feature": "buy_bonus",
                },
                "client_static_jungle_buy",
            ),
        ),
    )


def _chicken_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    prices = re.search(
        r"\{\s*buy_bonus\s*:\s*([0-9.]+)\s*,\s*"
        r"buy_super_bonus\s*:\s*([0-9.]+)\s*,\s*"
        r"buy_ultra_bonus\s*:\s*([0-9.]+)\s*\}",
        text,
    )
    if prices is None or "feature_id" not in text:
        return None

    modes: list[HyperHiveStaticMode] = []
    chance = re.search(
        r"\bJP\s*=\s*([0-9]+(?:\.[0-9]+)?)",
        text,
    )
    if chance is not None:
        modes.append(
            _mode(
                "buy_chance",
                "buy_chance",
                _clean_number(float(chance.group(1))),
                {
                    "bet_type": "bet",
                    "purchased_feature": "buy_chance",
                },
                "client_static_feature_map",
            )
        )

    for mode_id, price in zip(
        ("buy_bonus", "buy_super_bonus", "buy_ultra_bonus"),
        prices.groups(),
        strict=True,
    ):
        modes.append(
            _mode(
                mode_id,
                "buy_bonus",
                _clean_number(float(price)),
                {
                    "bet_type": "bet",
                    "purchased_feature": "buy_bonus",
                    "feature_id": mode_id,
                },
                "client_static_feature_map",
            )
        )

    return _profile(
        "client_static_feature_map",
        url,
        base={"bet_type": "bet"},
        base_complete=True,
        modes=modes,
    )


def _blazing_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    if "purchased_feature" not in text:
        return None
    if "buy_bonus" not in text or "buy_chance" not in text:
        return None

    buy = re.search(
        r"formatMoney\(\s*([0-9]+(?:\.[0-9]+)?)\s*\*\s*"
        r"[A-Za-z_$][\w$]*\s*\)",
        text,
    )
    chance = re.search(
        r"isAnteSpinActive\s*\?\s*([0-9]+(?:\.[0-9]+)?)\s*\*",
        text,
    )
    if buy is None or chance is None:
        return None

    return _profile(
        "client_static_blazing_feature_prices",
        url,
        base={"bet_type": "betting", "action": "spin"},
        base_complete=True,
        state_lock=True,
        modes=(
            _mode(
                "buy_chance",
                "buy_chance",
                _clean_number(float(chance.group(1))),
                {
                    "bet_type": "betting",
                    "purchased_feature": "buy_chance",
                },
                "client_static_blazing_feature_prices",
            ),
            _mode(
                "buy_bonus",
                "buy_bonus",
                _clean_number(float(buy.group(1))),
                {
                    "bet_type": "betting",
                    "purchased_feature": "buy_bonus",
                },
                "client_static_blazing_feature_prices",
            ),
        ),
    )


def _mystic_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    required = (
        "RESPIN_BUY",
        "BONUS_BUY",
        "request.bet",
        "buy_chance",
        "buy_bonus",
    )
    if not all(item in text for item in required):
        return None
    if re.search(
        r"request\.bet\s*=\s*\(request\.bet\s*\*\s*2\)\s*/\s*3",
        text,
    ) is None:
        return None
    if re.search(r"request\.bet\s*/=\s*100", text) is None:
        return None

    return _profile(
        "client_static_mode_transform",
        url,
        state_lock=True,
        modes=(
            _mode(
                "respin_buy",
                "buy_chance",
                1.5,
                {
                    "bet": "$BASE_BET_MUL_2_DIV_3",
                    "purchased_feature": "buy_chance",
                },
                "client_static_mode_transform",
            ),
            _mode(
                "bonus_buy",
                "buy_bonus",
                100,
                {
                    "bet": "$BASE_BET_DIV_100",
                    "purchased_feature": "buy_bonus",
                },
                "client_static_mode_transform",
            ),
        ),
    )


def _red_hot_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    if "purchased_feature" not in text:
        return None
    if "bonus_buy" not in text or "isSuperBonus" not in text:
        return None

    prices = re.search(
        r"isSuperBonus\s*\?\s*([0-9]+(?:\.[0-9]+)?)\s*:\s*"
        r"([0-9]+(?:\.[0-9]+)?)",
        text,
    )
    if prices is None:
        return None

    super_price = _clean_number(float(prices.group(1)))
    normal_price = _clean_number(float(prices.group(2)))
    return _profile(
        "client_static_bonus_buy_variants",
        url,
        base={"bet_type": "betting"},
        base_complete=True,
        state_lock=True,
        modes=(
            _mode(
                "bonus_buy",
                "bonus_buy",
                normal_price,
                {
                    "bet_type": "betting",
                    "isSuperBonus": False,
                    "purchased_feature": "bonus_buy",
                },
                "client_static_bonus_buy_variants",
            ),
            _mode(
                "super_bonus_buy",
                "bonus_buy",
                super_price,
                {
                    "bet_type": "betting",
                    "isSuperBonus": True,
                    "purchased_feature": "bonus_buy",
                },
                "client_static_bonus_buy_variants",
            ),
        ),
    )


def _clash_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    values = re.search(
        r"buyBonusModeMultiplier1\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"
        r"this\.buyBonusModeMultiplier2\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"
        r"this\.businessmanModeMultiplier1\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"
        r"this\.businessmanModeMultiplier2\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"
        r"this\.businessmanModeMultiplier3\s*=\s*([0-9]+(?:\.[0-9]+)?)",
        text,
    )
    if values is None or "feature_buy" not in text:
        return None

    buy1, buy2, ante1, ante0, ante2 = (
        _clean_number(float(value))
        for value in values.groups()
    )
    definitions = (
        ("ante_1", "buy_chance", ante1, 1),
        ("ante_0", "buy_chance", ante0, 1),
        ("ante_2", "buy_chance", ante2, 1),
        ("buy_bonus", "buy_bonus", buy1, buy1),
        ("super_buy_bonus", "buy_bonus", buy2, buy2),
    )
    modes = tuple(
        _mode(
            mode_id,
            feature,
            multiplier,
            {
                "bet_type": "default",
                "fe_exponent": "$FE_EXPONENT",
                "feature_buy": mode_id,
                "purchased_feature": feature,
                "buyBonusModeMultiplier": buy_multiplier,
            },
            "client_static_feature_buy_map",
        )
        for mode_id, feature, multiplier, buy_multiplier in definitions
    )

    return _profile(
        "client_static_feature_buy_map",
        url,
        base={
            "bet_type": "default",
            "fe_exponent": "$FE_EXPONENT",
            "purchased_feature": None,
            "buyBonusModeMultiplier": 1,
        },
        base_complete=True,
        modes=modes,
    )


def _legacy_obfuscated_rpc_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    required = (
        "_bgCallRpcMethod",
        "mConnectUrl",
        "bet_type",
        "'play'",
        "createEmptyObject",
    )
    if not all(marker in text for marker in required):
        return None
    if "freebet" not in text:
        return None

    return _profile(
        "client_static_legacy_rpc_manager",
        url,
        base={},
        base_complete=True,
        state_lock=True,
        modes=(),
    )


def _sweet_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    costs = re.search(
        r"BUY_BONUS_COSTS[^{}]{0,100}\{\s*"
        r"DEEP_SPIN\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"
        r"DEEP_BONANZA\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*\}",
        text,
    )
    if costs is None:
        return None
    if "deep_spin" not in text or "deep_bonanza" not in text:
        return None

    return _profile(
        "client_static_buy_bonus_costs",
        url,
        base={"bet_type": "bet"},
        base_complete=True,
        state_lock=True,
        wire_complete=False,
        modes=(
            _mode(
                "deep_spin",
                "buy_bonus",
                _clean_number(float(costs.group(1))),
                None,
                "client_static_buy_bonus_costs",
                complete=False,
                requirements=("game_specific_buy_bonus_wire",),
            ),
            _mode(
                "deep_bonanza",
                "buy_bonus",
                _clean_number(float(costs.group(2))),
                None,
                "client_static_buy_bonus_costs",
                complete=False,
                requirements=("game_specific_buy_bonus_wire",),
            ),
        ),
    )


def _zeus_profile(
    text: str,
    url: str,
) -> HyperHiveStaticProfile | None:
    if 'custom_field:"custom_value"' not in text:
        return None
    if "fe_exponent" not in text:
        return None
    if "network.invoke" not in text or '"play"' not in text:
        return None

    purchase_markers = (
        "purchased_feature",
        "buy_bonus",
        "buy_chance",
        "buyFeature",
        "buyBonus",
    )
    if any(marker in text for marker in purchase_markers):
        return None

    return _profile(
        "client_static_plain_spin_only",
        url,
        base={
            "bet_type": "default",
            "custom_field": "custom_value",
            "fe_exponent": "$FE_EXPONENT",
        },
        base_complete=True,
        modes=(),
    )


def _json_buy_profile(
    value: Any,
    url: str,
) -> HyperHiveStaticProfile | None:
    groups: list[Any] = []
    _collect_key(value, "buyFeatureInfo", groups)

    modes: list[HyperHiveStaticMode] = []
    for info in groups:
        if not isinstance(info, dict):
            continue
        configs = info.get("configs")
        if not isinstance(configs, list):
            continue
        for config in configs:
            if not isinstance(config, dict):
                continue
            feature = config.get("purchasedFeature")
            buy_id = config.get("buyFeatureId")
            percent = config.get("pricePercent")
            if not isinstance(feature, str):
                continue
            if buy_id is None or not _number(percent):
                continue
            modes.append(
                _mode(
                    str(buy_id),
                    feature,
                    _clean_number(float(percent) / 100.0),
                    {
                        "bet_type": "bet",
                        "purchased_feature": feature,
                        "buy_feature_id": buy_id,
                    },
                    "client_json_buy_feature_config",
                )
            )

    if not modes:
        return None
    return _profile(
        "client_json_buy_feature_config",
        url,
        base={"bet_type": "bet"},
        base_complete=True,
        state_lock=True,
        modes=_dedupe(modes),
    )


def _bet_slots_profile(
    value: Any,
    url: str,
) -> HyperHiveStaticProfile | None:
    groups: list[Any] = []
    _collect_key(value, "bet_slots", groups)

    modes: list[HyperHiveStaticMode] = []
    for slots in groups:
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            slot_type = str(slot.get("type") or "").casefold()
            rmid = slot.get("rmid")
            cmx = slot.get("cmx")
            if rmid is None or not _number(cmx):
                continue

            if slot_type == "bb":
                feature = "buy_bonus"
            elif slot_type == "ante":
                feature = "buy_chance"
            else:
                continue

            modes.append(
                _mode(
                    str(rmid).casefold(),
                    feature,
                    _clean_number(float(cmx)),
                    None,
                    "client_json_bet_slots",
                    complete=False,
                    requirements=("round_mode_id",),
                )
            )

    if not modes:
        return None
    return _profile(
        "client_json_bet_slots",
        url,
        modes=_dedupe(modes),
        wire_complete=False,
    )


def _buy_disabled_profile(
    value: Any,
    url: str,
) -> HyperHiveStaticProfile | None:
    if not isinstance(value, dict):
        return None
    bgaming = value.get("bg_gaming")
    if not isinstance(bgaming, dict):
        return None
    flag = bgaming.get("buy_btn")
    if flag is not False and str(flag).casefold() != "false":
        return None

    return _profile(
        "client_json_buy_disabled",
        url,
        modes=(),
        wire_complete=True,
    )


def _collect_key(
    value: Any,
    key: str,
    out: list[Any],
    depth: int = 0,
) -> None:
    if depth > 12:
        return
    if isinstance(value, list):
        for child in value[:300]:
            _collect_key(child, key, out, depth + 1)
        return
    if not isinstance(value, dict):
        return
    if key in value:
        out.append(value[key])
    for child in value.values():
        _collect_key(child, key, out, depth + 1)


def _number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )


def _clean_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _dedupe(
    modes: Iterable[HyperHiveStaticMode],
) -> tuple[HyperHiveStaticMode, ...]:
    out: list[HyperHiveStaticMode] = []
    seen: set[tuple[Any, ...]] = set()
    for mode in modes:
        key = (
            mode.mode_id,
            mode.feature,
            mode.multiplier,
            json.dumps(
                mode.request_fields,
                sort_keys=True,
                default=str,
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(mode)
    return tuple(out)
