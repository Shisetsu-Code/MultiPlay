from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

from ...models import EvidenceBundle


@dataclass(frozen=True, slots=True)
class HyperHiveStaticMode:
    kind: str
    feature: str
    mode_id: str
    multiplier: float | None
    request_fields: dict[str, Any] | None
    wire_complete: bool
    source: str
    evidence_url: str
    activation: bool = False
    bet_transform: str = ""
    wire_requirements: tuple[str, ...] = ()
    raw_bets: tuple[float, ...] = ()
    default_bet_raw: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = data.pop("mode_id")
        data["level"] = data["id"]
        data["wire_requirements"] = list(self.wire_requirements)
        data["raw_bets"] = list(self.raw_bets)
        return data


@dataclass(frozen=True, slots=True)
class HyperHiveStaticProfile:
    source: str | None
    catalog_complete: bool
    wire_complete: bool
    request_shape: tuple[str, ...] = ()
    modes: tuple[HyperHiveStaticMode, ...] = ()
    evidence_urls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "catalog_complete": self.catalog_complete,
            "wire_complete": self.wire_complete,
            "request_shape": list(self.request_shape),
            "modes": [mode.to_dict() for mode in self.modes],
            "evidence_urls": list(self.evidence_urls),
        }


@dataclass(frozen=True, slots=True)
class _Source:
    url: str
    body: str


Extractor = Callable[[str, str], HyperHiveStaticProfile | None]


def extract_hyperhive_static_profile(evidence: EvidenceBundle) -> HyperHiveStaticProfile:
    """Recover final Play-Ci HyperHive purchase knowledge from current client assets."""
    sources = _sources(evidence)
    extractors: tuple[Extractor, ...] = (
        _bet_slots,
        _buy_disabled,
        _jungle_queen,
        _joker_vs_joker,
        _red_hot_chilli,
        _mystic_reels,
        _clash_of_gods,
        _big_bucks,
        _blazing_firepots,
        _sweet_samurai,
        _yommi,
        _fs_multiplier,
        _json_buy_feature,
        _definitions,
        _configured_modes,
    )
    candidates = [
        profile
        for source in sources
        for extractor in extractors
        if (profile := extractor(source.body, source.url)) is not None
    ]
    if candidates:
        profile = max(
            candidates,
            key=lambda item: (
                100 * item.catalog_complete + 20 * item.wire_complete + len(item.modes)
            ),
        )
        return _resolve_definition_wire(profile, sources)

    no_buy = _oga_no_buy(sources)
    if no_buy is not None:
        return no_buy
    spin_only = _plain_spin_only(sources)
    if spin_only is not None:
        return spin_only
    return HyperHiveStaticProfile(None, False, False)


def seed_hyperhive_static_routes(
    routes: list[dict[str, Any]],
    profile: HyperHiveStaticProfile,
) -> None:
    """Add client-declared branches while keeping static evidence non-executable."""
    if not profile.modes:
        return

    if profile.catalog_complete:
        for route in routes:
            markers = {str(item) for item in route.get("wire_markers") or []}
            if (
                route.get("semantic") == "BUY_BONUS"
                and route.get("status") != "NETWORK_OBSERVED"
                and "method=play" in markers
                and not any(item.startswith("purchased_feature=") for item in markers)
            ):
                route["status"] = "CLIENT_CONTROL_STATIC_REPLACED"
                route["interface_role"] = "client_control"
                route["confidence"] = "MEDIUM"

    for mode in profile.modes:
        markers = _markers(mode)
        required = (
            {
                item
                for item in markers
                if item != "method=play" and not item.startswith("static_mode=")
            }
            if mode.wire_complete
            else {f"static_mode={mode.mode_id}"}
        )
        if any(
            required
            and required <= {str(item) for item in route.get("wire_markers") or []}
            for route in routes
        ):
            continue
        route_id = f"static:{_slug(profile.source)}:{_slug(mode.mode_id)}"
        routes.append(
            {
                "route_id": route_id,
                "semantic": "BUY_BONUS",
                "control": f"protocol:{mode.mode_id}",
                "handler": "",
                "chain": [],
                "status": (
                    "NETWORK_INFERRED"
                    if mode.wire_complete
                    else "CLIENT_DECLARED_WIRE_UNRESOLVED"
                ),
                "interface_role": "network_action",
                "confidence": "HIGH" if mode.wire_complete else "MEDIUM",
                "wire_markers": sorted(markers),
                "static_mode": mode.to_dict(),
                "direct_executable": False,
                "direct_reason": (
                    "static client wire requires direct demo validation"
                    if mode.wire_complete
                    else "client catalog is known but request wire is unresolved"
                ),
            }
        )


def _sources(evidence: EvidenceBundle) -> list[_Source]:
    found: list[_Source] = []
    seen: set[tuple[str, str]] = set()
    for script in evidence.scripts:
        item = (str(script.source or ""), str(script.text or ""))
        if len(item[1]) >= 20 and item not in seen:
            seen.add(item)
            found.append(_Source(*item))
    for exchange in evidence.http:
        url = str(exchange.url or "")
        if not re.search(r"\.(?:js|mjs|json)(?:\?|$)", url, re.IGNORECASE):
            continue
        value = exchange.response_body
        body = (
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if isinstance(value, (dict, list))
            else str(value or "")
        )
        item = (url, body)
        if len(body) >= 20 and item not in seen:
            seen.add(item)
            found.append(_Source(*item))
    return found


def _profile(
    source: str,
    modes: list[HyperHiveStaticMode],
    *,
    catalog: bool = True,
    wire: bool = True,
    shape: tuple[str, ...] = (),
    urls: tuple[str, ...] = (),
) -> HyperHiveStaticProfile:
    unique: dict[str, HyperHiveStaticMode] = {}
    for mode in modes:
        key = json.dumps(
            [mode.feature, mode.mode_id, mode.multiplier, mode.request_fields],
            sort_keys=True,
            default=str,
        )
        unique.setdefault(key, mode)
    return HyperHiveStaticProfile(source, catalog, wire, shape, tuple(unique.values()), urls)


def _mode(
    source: str,
    url: str,
    feature: str,
    mode_id: str,
    multiplier: float | int | None,
    request_fields: dict[str, Any] | None,
    *,
    kind: str = "buy",
    wire: bool = True,
    activation: bool = False,
    transform: str = "",
    requires: tuple[str, ...] = (),
    raw_bets: tuple[float, ...] = (),
    default_bet: float | None = None,
) -> HyperHiveStaticMode:
    return HyperHiveStaticMode(
        kind=kind,
        feature=feature,
        mode_id=mode_id,
        multiplier=float(multiplier) if multiplier is not None else None,
        request_fields=request_fields,
        wire_complete=wire,
        source=source,
        evidence_url=url,
        activation=activation,
        bet_transform=transform,
        wire_requirements=requires,
        raw_bets=raw_bets,
        default_bet_raw=default_bet,
    )


def _configured_modes(source: str, url: str) -> HyperHiveStaticProfile | None:
    if "purchaseFeaturesConfig" not in source:
        return None
    direct = bool(re.search(r"recycle-riches\.", url, re.IGNORECASE))
    modes: list[HyperHiveStaticMode] = []
    for match in re.finditer(
        r"\{[^{}]{0,1800}(?:configFeatureType|betPriceMultiplier)\s*:[^{}]{0,1800}\}",
        source,
    ):
        text = match.group(0)
        mode_id = _literal(_field(text, "id"))
        feature = _literal(_field(text, "type"))
        price = _num(_literal(_field(text, "price") or _field(text, "betPriceMultiplier")))
        if not isinstance(mode_id, str) or not isinstance(feature, str) or price is None:
            continue
        if not feature.casefold().startswith("buy_"):
            continue
        modes.append(
            _mode(
                (
                    "client_static_purchase_config+validated_direct_wire"
                    if direct
                    else "client_static_purchase_config"
                ),
                url,
                feature,
                mode_id,
                price,
                {"purchased_feature": feature, "custom_field": mode_id},
                kind="booster" if feature == "buy_chance" else "buy",
                wire=direct,
                activation=feature == "buy_chance",
                requires=() if direct else ("requestData", "bet_type"),
            )
        )
    if not modes:
        return None
    name = modes[0].source
    return _profile(
        name,
        modes,
        wire=direct,
        shape=("custom_field", "purchased_feature"),
        urls=(url,),
    )


def _bet_slots(source: str, url: str) -> HyperHiveStaticProfile | None:
    body = _json(source)
    slots = body.get("bet_slots") if isinstance(body, dict) else None
    if not isinstance(slots, list) or len(slots) < 2:
        return None
    modes: list[HyperHiveStaticMode] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        slot_type = str(slot.get("type") or "").casefold()
        rmid = str(slot.get("rmid") or "").strip()
        multiplier = _num(slot.get("cmx"))
        if not rmid or multiplier is None or multiplier <= 0:
            continue
        if slot_type == "bb":
            kind, feature, activation = "buy", "buy_bonus", False
        elif slot_type == "ante":
            kind, feature, activation = "booster", "buy_chance", True
        else:
            continue
        raw_bets = tuple(
            number
            for value in slot.get("tbvs", [])
            if (number := _num(value)) is not None
        )
        modes.append(
            _mode(
                "client_json_bet_slots",
                url,
                feature,
                rmid.casefold(),
                multiplier,
                None,
                kind=kind,
                wire=False,
                activation=activation,
                requires=("round_mode_id",),
                raw_bets=raw_bets,
                default_bet=_num(slot.get("tb")),
            )
        )
    return (
        _profile("client_json_bet_slots", modes, wire=False, urls=(url,))
        if modes
        else None
    )


def _definitions(source: str, url: str) -> HyperHiveStaticProfile | None:
    body = _json(source)
    definition = (
        body.get("engine", {}).get("definition")
        if isinstance(body, dict) and isinstance(body.get("engine"), dict)
        else None
    )
    if not isinstance(definition, dict):
        return None
    modes: list[HyperHiveStaticMode] = []
    normal = _num(definition.get("normalBuyCost"))
    super_buy = _num(definition.get("superBuyCost"))
    if normal is not None and super_buy is not None:
        for mode_id, multiplier in (("normal", normal), ("super", super_buy)):
            modes.append(
                _mode(
                    "engine_definition_buy_costs",
                    url,
                    "buy_bonus",
                    mode_id,
                    multiplier,
                    {"purchased_feature": "buy_bonus"},
                    wire=False,
                    requires=("custom_req.buy_mode",),
                )
            )
    free = _num(definition.get("featureBuyMulFreespin"))
    respin = _num(definition.get("featureBuyMulRespin"))
    if free is not None and respin is not None:
        for mode_id, multiplier, requirement in (
            ("freespin", free, "custom_req.isFeatureBuyFreeSpin"),
            ("respin", respin, "custom_req.isFeatureBuyRespin"),
        ):
            modes.append(
                _mode(
                    "engine_definition_feature_buy_multipliers",
                    url,
                    "buy_bonus",
                    mode_id,
                    multiplier,
                    {"purchased_feature": "buy_bonus"},
                    wire=False,
                    requires=(requirement,),
                )
            )
    return _profile(modes[0].source, modes, wire=False, urls=(url,)) if modes else None


def _resolve_definition_wire(
    profile: HyperHiveStaticProfile,
    sources: list[_Source],
) -> HyperHiveStaticProfile:
    if profile.wire_complete or profile.source != "engine_definition_feature_buy_multipliers":
        return profile
    clients = [
        item
        for item in sources
        if "customizeFeatureBuyRequestData" in item.body
        and "isFeatureBuyFreeSpin" in item.body
        and "isFeatureBuyRespin" in item.body
    ]
    if not clients:
        return profile
    modes = [
        _mode(
            "client_static_feature_buy_flags",
            mode.evidence_url,
            "buy_bonus",
            mode.mode_id,
            mode.multiplier,
            {
                "bet": "<PURCHASE_BET_SUBUNITS>",
                "purchased_feature": "buy_bonus",
                "bet_type": "bet",
                "custom_req": {
                    "selectedWinLines": None,
                    "perLine": True,
                    "isFeatureBuyFreeSpin": mode.mode_id == "freespin",
                    "isFeatureBuyRespin": mode.mode_id == "respin",
                    "action": "spin",
                    "exponent": "<CURRENCY_EXPONENT>",
                    "stake": "<PURCHASE_BET_SUBUNITS>",
                },
            },
            transform="base_bet * multiplier",
        )
        for mode in profile.modes
    ]
    urls = tuple(dict.fromkeys([*profile.evidence_urls, *(item.url for item in clients)]))
    return _profile(
        "client_static_feature_buy_flags",
        modes,
        shape=(
            "purchased_feature",
            "bet_type",
            "custom_req.isFeatureBuyFreeSpin",
            "custom_req.isFeatureBuyRespin",
            "custom_req.action",
            "custom_req.exponent",
            "custom_req.stake",
        ),
        urls=urls,
    )


def _yommi(source: str, url: str) -> HyperHiveStaticProfile | None:
    if "FEATURE_BET_MULTIPLIER" not in source or "PURCHASED_FEATURES" not in source:
        return None
    prices = re.search(
        r"FEATURE_BET_MULTIPLIER\s*=\s*[^;]{0,1200}?BONUS\s*,\s*(\d+)n?"
        r"[^;]{0,600}?SUPER_BONUS\s*,\s*(\d+)n?"
        r"[^;]{0,600}?MORE_PETS\s*,\s*(\d+)n?",
        source,
    )
    if prices is None:
        return None
    values = {
        "bonus": prices.group(1),
        "super_bonus": prices.group(2),
        "more_pets": prices.group(3),
    }
    mappings = {
        "more_pets": "buy_chance",
        "bonus": "buy_bonus",
        "super_bonus": "buy_bonus_and_chance",
    }
    has_model = "modelRev" in source
    has_min = "minExponent" in source
    modes: list[HyperHiveStaticMode] = []
    for mode_id in ("more_pets", "bonus", "super_bonus"):
        feature = mappings[mode_id]
        fields: dict[str, Any] = {"purchased_feature": feature, "bet_type": "bet"}
        if has_model:
            fields["modelRev"] = 0
        if has_min:
            fields["minExponent"] = 2
        modes.append(
            _mode(
                "client_static_feature_multiplier_map",
                url,
                feature,
                mode_id,
                float(values[mode_id]),
                fields,
                kind="booster" if feature == "buy_chance" else "buy",
                activation=feature == "buy_chance",
            )
        )
    shape = tuple(
        name
        for name, present in (("modelRev", has_model), ("minExponent", has_min))
        if present
    )
    return _profile(
        "client_static_feature_multiplier_map",
        modes,
        shape=shape,
        urls=(url,),
    )


def _fs_multiplier(source: str, url: str) -> HyperHiveStaticProfile | None:
    value = re.search(r"\bfsMultiplier\s*=\s*([0-9]+(?:\.[0-9]+)?)", source)
    if value is None:
        return None
    if not re.search(r"purchasedFeatures\.some\([^)]*[\"']buy_bonus[\"']", source):
        return None
    if "purchased_feature" not in source or float(value.group(1)) <= 1:
        return None
    bet_type = (
        "default"
        if re.search(r"bet_type[^\"']{0,120}[\"']default[\"']", source)
        else "bet"
    )
    mode = _mode(
        "client_static_fs_multiplier",
        url,
        "buy_bonus",
        "buy_bonus",
        float(value.group(1)),
        {"purchased_feature": "buy_bonus", "bet_type": bet_type},
    )
    return _profile(
        "client_static_fs_multiplier",
        [mode],
        shape=("purchased_feature", "bet_type"),
        urls=(url,),
    )


def _big_bucks(source: str, url: str) -> HyperHiveStaticProfile | None:
    values = [
        float(item)
        for item in re.findall(
            r"\bbuyBonusMultiplier\s*=\s*([0-9]+(?:\.[0-9]+)?)",
            source,
        )
        if float(item) > 1
    ]
    if not values or "bonusPrices.freespin_buy" not in source:
        return None
    if not re.search(r"purchased_feature\s*:\s*[\"']buy_bonus[\"']", source):
        return None
    mode = _mode(
        "client_static_buy_bonus_multiplier",
        url,
        "buy_bonus",
        "buy_bonus",
        max(values),
        {"purchased_feature": "buy_bonus"},
    )
    return _profile(
        "client_static_buy_bonus_multiplier",
        [mode],
        shape=("purchased_feature",),
        urls=(url,),
    )


def _blazing_firepots(source: str, url: str) -> HyperHiveStaticProfile | None:
    if not re.search(r"purchased_feature\s*:\s*[\"']buy_bonus[\"']", source):
        return None
    if not re.search(r"purchased_feature\s*:\s*[\"']buy_chance[\"']", source):
        return None
    buy = re.search(
        r"formatMoney\(\s*([0-9]+(?:\.[0-9]+)?)\s*\*\s*[A-Za-z_$][\w$]*\s*\)",
        source,
    )
    chance = re.search(
        r"isAnteSpinActive\s*\?\s*([0-9]+(?:\.[0-9]+)?)"
        r"\s*\*\s*[A-Za-z_$][\w$]*",
        source,
    )
    if buy is None or chance is None:
        return None
    modes = [
        _mode(
            "client_static_blazing_feature_prices",
            url,
            "buy_chance",
            "buy_chance",
            float(chance.group(1)),
            {"purchased_feature": "buy_chance", "bet_type": "betting"},
            kind="booster",
            activation=True,
        ),
        _mode(
            "client_static_blazing_feature_prices",
            url,
            "buy_bonus",
            "buy_bonus",
            float(buy.group(1)),
            {"purchased_feature": "buy_bonus", "bet_type": "betting"},
        ),
    ]
    return _profile(
        "client_static_blazing_feature_prices",
        modes,
        shape=("purchased_feature", "bet_type"),
        urls=(url,),
    )


def _sweet_samurai(source: str, url: str) -> HyperHiveStaticProfile | None:
    costs = re.search(
        r"BUY_BONUS_COSTS[\"']?\s*,?\s*\{\s*DEEP_SPIN\s*:\s*"
        r"([0-9.]+)\s*,\s*DEEP_BONANZA\s*:\s*([0-9.]+)\s*\}",
        source,
    ) or re.search(
        r"BUY_BONUS_COSTS[^{}]{0,100}\{\s*DEEP_SPIN\s*:\s*"
        r"([0-9.]+)\s*,\s*DEEP_BONANZA\s*:\s*([0-9.]+)\s*\}",
        source,
    )
    if costs is None:
        return None
    if not re.search(r"DEEP_SPIN\s*=\s*[\"']deep_spin[\"']", source):
        return None
    if not re.search(r"DEEP_BONANZA\s*=\s*[\"']deep_bonanza[\"']", source):
        return None
    modes = [
        _mode(
            "client_static_buy_bonus_costs",
            url,
            "buy_bonus",
            "deep_spin",
            float(costs.group(1)),
            None,
            wire=False,
            requires=("game_specific_buy_bonus_wire",),
        ),
        _mode(
            "client_static_buy_bonus_costs",
            url,
            "buy_bonus",
            "deep_bonanza",
            float(costs.group(2)),
            None,
            wire=False,
            requires=("game_specific_buy_bonus_wire",),
        ),
    ]
    return _profile(
        "client_static_buy_bonus_costs",
        modes,
        wire=False,
        urls=(url,),
    )


def _mystic_reels(source: str, url: str) -> HyperHiveStaticProfile | None:
    required = (
        "RESPIN_BUY" in source,
        "BONUS_BUY" in source,
        bool(
            re.search(
                r"request\.bet\s*=\s*\(request\.bet\s*\*\s*2\)\s*/\s*3",
                source,
            )
        ),
        bool(re.search(r"request\.bet\s*/=\s*100", source)),
    )
    if not all(required):
        return None
    if not re.search(
        r"(?:RESPIN_BUY[\"']?\s*:\s*return|"
        r"case\s*[\"']RESPIN_BUY[\"']\s*:\s*return)"
        r"\s*[\"']buy_chance[\"']",
        source,
    ):
        return None
    if not re.search(
        r"case\s*[\"']BONUS_BUY[\"']\s*:\s*return\s*[\"']buy_bonus[\"']",
        source,
    ):
        return None
    modes = [
        _mode(
            "client_static_mode_transform",
            url,
            "buy_chance",
            "respin_buy",
            1.5,
            {"bet": "<BASE_BET_SUBUNITS>", "purchased_feature": "buy_chance"},
            kind="booster",
            activation=True,
            transform="visible_stake / 1.5",
        ),
        _mode(
            "client_static_mode_transform",
            url,
            "buy_bonus",
            "bonus_buy",
            100,
            {"bet": "<BASE_BET_SUBUNITS>", "purchased_feature": "buy_bonus"},
            transform="visible_stake / 100",
        ),
    ]
    return _profile(
        "client_static_mode_transform",
        modes,
        shape=("purchased_feature", "bet_transform"),
        urls=(url,),
    )


def _clash_of_gods(source: str, url: str) -> HyperHiveStaticProfile | None:
    values = re.search(
        r"buyBonusModeMultiplier1\s*=\s*([0-9.]+)\s*,\s*"
        r"this\.buyBonusModeMultiplier2\s*=\s*([0-9.]+)\s*,\s*"
        r"this\.businessmanModeMultiplier1\s*=\s*([0-9.]+)\s*,\s*"
        r"this\.businessmanModeMultiplier2\s*=\s*([0-9.]+)\s*,\s*"
        r"this\.businessmanModeMultiplier3\s*=\s*([0-9.]+)",
        source,
    )
    patterns = (
        r"ante_0=[\"']ante_0[\"']",
        r"ante_1=[\"']ante_1[\"']",
        r"ante_2=[\"']ante_2[\"']",
        r"buy_bonus=[\"']buy_bonus[\"']",
        r"super_buy_bonus=[\"']super_buy_bonus[\"']",
    )
    if values is None or not all(re.search(pattern, source) for pattern in patterns):
        return None
    buy1, buy2, ante1, ante0, ante2 = [
        float(values.group(index))
        for index in range(1, 6)
    ]
    definitions = (
        ("booster", "buy_chance", "ante_1", ante1, 1),
        ("booster", "buy_chance", "ante_0", ante0, 1),
        ("booster", "buy_chance", "ante_2", ante2, 1),
        ("buy", "buy_bonus", "buy_bonus", buy1, buy1),
        ("buy", "buy_bonus", "super_buy_bonus", buy2, buy2),
    )
    modes = [
        _mode(
            "client_static_feature_buy_map",
            url,
            feature,
            mode_id,
            multiplier,
            {
                "bet_type": "default",
                "fe_exponent": "<FE_EXPONENT>",
                "bonus_type": "<BONUS_TYPE>",
                "feature_buy": mode_id,
                "purchased_feature": feature,
                "buyBonusModeMultiplier": buy_multiplier,
            },
            kind=kind,
            activation=kind == "booster",
        )
        for kind, feature, mode_id, multiplier, buy_multiplier in definitions
    ]
    return _profile(
        "client_static_feature_buy_map",
        modes,
        shape=(
            "feature_buy",
            "purchased_feature",
            "buyBonusModeMultiplier",
            "bonus_type",
            "fe_exponent",
        ),
        urls=(url,),
    )


def _red_hot_chilli(source: str, url: str) -> HyperHiveStaticProfile | None:
    prices = re.search(
        r"isSuperBonus\s*\?\s*([0-9.]+)\s*:\s*([0-9.]+)",
        source,
    )
    if prices is None:
        return None
    if not re.search(r"purchased_feature\s*:\s*[\"']bonus_buy[\"']", source):
        return None
    bet_type = (
        "betting"
        if re.search(r"bet_type\s*:\s*[\"']betting[\"']", source)
        else "bet"
    )
    modes = [
        _mode(
            "client_static_bonus_buy_variants",
            url,
            "bonus_buy",
            "bonus_buy",
            float(prices.group(2)),
            {
                "purchased_feature": "bonus_buy",
                "isSuperBonus": False,
                "bet_type": bet_type,
            },
        ),
        _mode(
            "client_static_bonus_buy_variants",
            url,
            "bonus_buy",
            "super_bonus_buy",
            float(prices.group(1)),
            {
                "purchased_feature": "bonus_buy",
                "isSuperBonus": True,
                "bet_type": bet_type,
            },
        ),
    ]
    return _profile(
        "client_static_bonus_buy_variants",
        modes,
        shape=("purchased_feature", "isSuperBonus", "bet_type"),
        urls=(url,),
    )


def _joker_vs_joker(source: str, url: str) -> HyperHiveStaticProfile | None:
    values = re.search(
        r"busnesssmanModeMultiplier\s*=\s*([0-9.]+)\s*,\s*"
        r"this\.buyBonusModeMultiplier\s*=\s*([0-9.]+)",
        source,
    )
    if values is None:
        return None
    if not re.search(r"businessmanMode\s*\?\s*[\"']buy_chance[\"']", source):
        return None
    if "purchased_feature" not in source:
        return None
    common = {
        "bet_type": "default",
        "fe_exponent": "<FE_EXPONENT>",
        "balance": "<BALANCE>",
    }
    booster, buy = float(values.group(1)), float(values.group(2))
    modes = [
        _mode(
            "client_static_joker_mode_multipliers",
            url,
            "buy_chance",
            "businessman_mode",
            booster,
            {
                **common,
                "purchased_feature": "buy_chance",
                "buyBonusModeMultiplier": 1,
            },
            kind="booster",
            activation=True,
        ),
        _mode(
            "client_static_joker_mode_multipliers",
            url,
            "buy_bonus",
            "buy_bonus",
            buy,
            {
                **common,
                "purchased_feature": "buy_bonus",
                "buyBonusModeMultiplier": buy,
            },
        ),
    ]
    return _profile(
        "client_static_joker_mode_multipliers",
        modes,
        shape=(
            "purchased_feature",
            "buyBonusModeMultiplier",
            "fe_exponent",
            "balance",
        ),
        urls=(url,),
    )


def _jungle_queen(source: str, url: str) -> HyperHiveStaticProfile | None:
    multiplier = re.search(r"\bua\s*=\s*([0-9.]+)", source)
    if multiplier is None:
        return None
    if not re.search(
        r"const\s+[A-Za-z_$][\w$]*\s*=\s*[\"']buybonus[\"']\s*,\s*"
        r"[A-Za-z_$][\w$]*\s*=\s*[\"']buybonus[\"']",
        source,
    ):
        return None
    if not re.search(
        r"action\s*:\s*[A-Za-z_$][\w$]*\s*,\s*"
        r"id\s*:\s*[A-Za-z_$][\w$]*",
        source,
    ):
        return None
    if not re.search(r"purchased_feature\s*:\s*[\"']buy_bonus[\"']", source):
        return None
    mode = _mode(
        "client_static_jungle_buy",
        url,
        "buy_bonus",
        "buybonus",
        float(multiplier.group(1)),
        {
            "action": "buybonus",
            "id": "buybonus",
            "purchased_feature": "buy_bonus",
        },
    )
    return _profile(
        "client_static_jungle_buy",
        [mode],
        shape=("action", "id", "purchased_feature"),
        urls=(url,),
    )


def _json_buy_feature(source: str, url: str) -> HyperHiveStaticProfile | None:
    body = _json(source)
    if body is None:
        return None
    configs: list[dict[str, Any]] = []

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 12:
            return
        if isinstance(value, list):
            for child in value[:200]:
                visit(child, depth + 1)
        elif isinstance(value, dict):
            info = value.get("buyFeatureInfo")
            if isinstance(info, dict) and isinstance(info.get("configs"), list):
                configs.extend(
                    item
                    for item in info["configs"]
                    if isinstance(item, dict)
                )
            for child in value.values():
                visit(child, depth + 1)

    visit(body)
    modes: list[HyperHiveStaticMode] = []
    for item in configs:
        feature = item.get("purchasedFeature")
        mode_id = item.get("buyFeatureId")
        percent = _num(item.get("pricePercent"))
        if not isinstance(feature, str) or mode_id is None or percent is None:
            continue
        modes.append(
            _mode(
                "client_json_buy_feature_config",
                url,
                feature,
                str(mode_id),
                round(percent / 100, 8),
                {
                    "purchased_feature": feature,
                    "buy_feature_id": mode_id,
                },
                kind="booster" if feature == "buy_chance" else "buy",
                activation=feature == "buy_chance",
            )
        )
    return (
        _profile(
            "client_json_buy_feature_config",
            modes,
            shape=("buy_feature_id",),
            urls=(url,),
        )
        if modes
        else None
    )


def _buy_disabled(source: str, url: str) -> HyperHiveStaticProfile | None:
    body = _json(source)
    bg = body.get("bg_gaming") if isinstance(body, dict) else None
    if isinstance(bg, dict):
        value = bg.get("buy_btn")
        if value is False or str(value).casefold() == "false":
            return _profile(
                "client_json_buy_disabled",
                [],
                urls=(url,),
            )
    return None


def _oga_no_buy(sources: list[_Source]) -> HyperHiveStaticProfile | None:
    definitions: tuple[_Source, dict[str, Any]] | None = None
    config: tuple[_Source, dict[str, Any]] | None = None
    client: _Source | None = None
    game: _Source | None = None
    for source in sources:
        if re.search(
            r"definitions(?:\.[^/?]+)?\.json(?:\?|$)",
            source.url,
            re.IGNORECASE,
        ):
            body = _json(source.body)
            if isinstance(body, dict) and isinstance(body.get("engine"), dict):
                definitions = source, body
        elif re.search(r"gameConfig\.json(?:\?|$)", source.url, re.IGNORECASE):
            body = _json(source.body)
            if isinstance(body, dict):
                config = source, body
        elif re.search(r"client\.min\.js(?:\?|$)", source.url, re.IGNORECASE):
            if (
                "definitionsGameData.engine.definition.featureBuyMulRespin"
                in source.body
                and "definitionsGameData.engine.definition.featureBuyMulFreespin"
                in source.body
            ):
                client = source
        elif re.search(r"game\.min\.js(?:\?|$)", source.url, re.IGNORECASE):
            game = source
    if not all((definitions, config, client, game)):
        return None
    assert definitions is not None
    assert config is not None
    assert client is not None
    assert game is not None
    autoplay = config[1].get("autoplay")
    definition = definitions[1].get("engine", {}).get("definition")
    if (
        not isinstance(autoplay, dict)
        or autoplay.get("onBonusFeature") is not False
        or not isinstance(definition, dict)
    ):
        return None
    pattern = re.compile(
        r"feature.*buy|buy.*feature|buy.*cost|"
        r"featureBuyMul|normalBuyCost|superBuyCost",
        re.IGNORECASE,
    )
    if any(pattern.search(str(key)) for key in _deep_keys(definition)):
        return None
    markers = re.compile(
        r"isFeatureBuyRespin|isFeatureBuyFreeSpin|"
        r"featureBuyMulRespin|featureBuyMulFreespin|"
        r"purchaseFeaturesConfig|buyFeatureId|buy_feature_id|"
        r"bonus_multiplier_type|feature_id\s*:",
        re.IGNORECASE,
    )
    if markers.search(game.body):
        return None
    return _profile(
        "client_oga_no_feature_buy_definition",
        [],
        urls=(definitions[0].url, config[0].url, client.url, game.url),
    )


def _plain_spin_only(sources: list[_Source]) -> HyperHiveStaticProfile | None:
    purchase = re.compile(
        r"purchased_feature|buy_bonus|buy_chance|buy_bonus_and_chance|"
        r"purchaseFeature|buyFeature|buyBonus|bonus_buy|freespin_buy",
        re.IGNORECASE,
    )
    for source in sources:
        if not re.search(r"\.(?:js|mjs)(?:\?|$)", source.url, re.IGNORECASE):
            continue
        if not re.search(r"network\.invoke\([\"']play[\"']", source.body):
            continue
        if not re.search(
            r"custom_field\s*:\s*[\"']custom_value[\"']",
            source.body,
        ):
            continue
        if purchase.search(source.body):
            continue
        return _profile(
            "client_static_plain_spin_only",
            [],
            shape=("bet", "bet_type", "custom_field", "fe_exponent"),
            urls=(source.url,),
        )
    return None


def _markers(mode: HyperHiveStaticMode) -> set[str]:
    markers = {"method=play", f"static_mode={mode.mode_id}"}

    def visit(value: Any, prefix: str = "") -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, dict):
                visit(child, name)
            elif isinstance(child, str) and child.startswith("<") and child.endswith(">"):
                continue
            elif child is None:
                markers.add(f"{name}=null")
            elif isinstance(child, bool):
                rendered = "true" if child else "false"
                markers.add(f"{name}={rendered}")
            elif isinstance(child, (str, int, float)):
                markers.add(f"{name}={child}")

    visit(mode.request_fields)
    if not any(item.startswith("purchased_feature=") for item in markers):
        markers.add(f"purchased_feature={mode.feature}")
    return markers


def _field(text: str, key: str) -> str | None:
    token = (
        r'(?:(?:"(?:\\.|[^"])*")|'
        r"(?:'(?:\\.|[^'])*')|-?\d+(?:\.\d+)?|"
        r"!0|!1|true|false|[A-Za-z_$][\w$]*)"
    )
    match = re.search(rf"\b{re.escape(key)}\s*:\s*({token})", text)
    return match.group(1) if match else None


def _literal(value: str | None) -> Any:
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if value in {"true", "!0"}:
        return True
    if value in {"false", "!1"}:
        return False
    return _num(value)


def _json(source: str) -> Any:
    try:
        return json.loads(source)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _deep_keys(value: Any, depth: int = 0) -> list[str]:
    if depth > 12:
        return []
    if isinstance(value, list):
        return [
            key
            for child in value
            for key in _deep_keys(child, depth + 1)
        ]
    if not isinstance(value, dict):
        return []
    return [str(key) for key in value] + [
        nested
        for child in value.values()
        for nested in _deep_keys(child, depth + 1)
    ]


def _slug(value: str | None) -> str:
    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value or "static").casefold(),
    ).strip("-")
    return text or "static"
