import json

from multiplay.models import EvidenceBundle, HttpExchange, ScriptEvidence
from multiplay.providers.bgaming.auto_analyze import (
    _seed_hyperhive_static_routes,
)
from multiplay.providers.bgaming.hyperhive_static import (
    discover_hyperhive_static_profile,
    discover_hyperhive_static_sources,
)


def _script(text: str) -> EvidenceBundle:
    return EvidenceBundle(
        scripts=[
            ScriptEvidence(
                evidence_id="s",
                source="https://example.bgaming-network.com/app.js",
                text=text,
            )
        ]
    )


def test_discovers_blackbeard_style_bonus_multiplier_wire():
    evidence = _script(
        'cfg={goldenBetMulti:1.5};'
        'const e=x,t=100*e.bet,n=200*e.bet;'
        'play({bet:e.bet,bet_type:"bet",purchased_feature:"buy_chance"});'
        'play({bet:e.bet,bet_type:"bet",purchased_feature:"buy_bonus",'
        'bonus_multiplier_type:"freeSpin"});'
        'play({bet:e.bet,bet_type:"bet",purchased_feature:"buy_bonus",'
        'bonus_multiplier_type:"freeSpinRandom"});'
    )

    profile = discover_hyperhive_static_profile(evidence)

    assert profile is not None
    assert profile.base_request_fields == {"bet_type": "bet"}
    assert [mode.multiplier for mode in profile.modes] == [1.5, 100, 200]
    assert profile.modes[2].request_fields == {
        "bet_type": "bet",
        "purchased_feature": "buy_bonus",
        "bonus_multiplier_type": "freeSpinRandom",
    }


def test_discovers_feature_id_purchase_family():
    evidence = _script(
        'const JP=1.5,QP={buy_bonus:60,buy_super_bonus:90,buy_ultra_bonus:120};'
        'function base(){return {bet:1,bet_type:"bet"}}'
        'function buy(t,e){t.purchased_feature=e.purchased_feature;'
        't.feature_id=e.feature_id;return t}'
    )

    profile = discover_hyperhive_static_profile(evidence)

    assert profile is not None
    assert profile.source == "client_static_feature_map"
    assert [mode.mode_id for mode in profile.modes] == [
        "buy_chance",
        "buy_bonus",
        "buy_super_bonus",
        "buy_ultra_bonus",
    ]
    assert profile.modes[-1].request_fields["feature_id"] == "buy_ultra_bonus"


def test_discovers_bonus_buy_selector_catalog():
    evidence = _script(
        'async play(t,e,s){const n={bet:t,purchased_feature:e,bonus_buy:s};}'
        'function features(){return ['
        '{id:"wild_booster_x3",price:6,purchaseFeature:"buy_chance",activation:true},'
        '{id:"wild_booster_x5",price:24,purchaseFeature:"buy_chance",activation:true},'
        '{id:"full_drop",price:200,purchaseFeature:"buy_bonus",activation:true},'
        '{id:"drop_dead",price:92,purchaseFeature:"buy_bonus_and_chance",activation:true}'
        ']}'
    )

    profile = discover_hyperhive_static_profile(evidence)

    assert profile is not None
    assert [mode.multiplier for mode in profile.modes] == [6, 24, 200, 92]
    assert profile.modes[-1].request_fields == {
        "purchased_feature": "buy_bonus_and_chance",
        "bonus_buy": "drop_dead",
    }


def test_discovers_buy_feature_info_from_json_response():
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="config",
                method="GET",
                url="https://example.bgaming-network.com/slot_assets/gameConfig.json",
                response_status=200,
                response_body={
                    "game": {
                        "buyFeatureInfo": {
                            "configs": [
                                {
                                    "purchasedFeature": "buy_bonus",
                                    "buyFeatureId": 7,
                                    "pricePercent": 10000,
                                }
                            ]
                        }
                    }
                },
            )
        ]
    )

    profile = discover_hyperhive_static_profile(evidence)

    assert profile is not None
    assert profile.state_lock_required is True
    assert profile.modes[0].multiplier == 100
    assert profile.modes[0].request_fields["buy_feature_id"] == 7


def test_plain_spin_profile_keeps_client_literals():
    evidence = _script(
        'network.invoke("play",{token:t,req:{bet:e,bet_type:"default",'
        'custom_field:"custom_value",fe_exponent:f}})'
    )

    profile = discover_hyperhive_static_profile(evidence)

    assert profile is not None
    assert profile.modes == ()
    assert profile.base_request_fields == {
        "bet_type": "default",
        "custom_field": "custom_value",
        "fe_exponent": "$FE_EXPONENT",
    }


def test_static_profile_seeds_executable_and_unresolved_routes():
    evidence = _script(
        'e("BUY_BONUS_COSTS",{DEEP_SPIN:100,DEEP_BONANZA:150});'
        'enumx={DEEP_SPIN:"deep_spin",DEEP_BONANZA:"deep_bonanza"}'
    )
    profile = discover_hyperhive_static_profile(evidence)
    assert profile is not None

    routes = []
    _seed_hyperhive_static_routes(routes, profile)

    assert len(routes) == 2
    assert all(route["static_wire_complete"] is False for route in routes)
    assert {route["declared_multiplier"] for route in routes} == {100, 150}


def test_profile_serialization_is_json_safe():
    evidence = _script(
        'network.invoke("play",{token:t,req:{bet:e,bet_type:"default",'
        'custom_field:"custom_value",fe_exponent:f}})'
    )
    profile = discover_hyperhive_static_profile(evidence)
    assert profile is not None

    json.dumps(profile.to_dict())


def test_legacy_bet_slots_use_numeric_bid_serializer():
    profile = discover_hyperhive_static_sources(
        [
            (
                "https://example.bgaming-network.com/bs_lib.js",
                (
                    "_bgCallRpcMethod mConnectUrl bet_type 'play' "
                    "createEmptyObject freebet bet_slots "
                    "eBetsIDs={'DEFAULT':0x0,'SHOP':0x1}"
                ),
            ),
            (
                "https://example.bgaming-network.com/init.json",
                {
                    "settings": {
                        "bet_slots": [
                            {"id": 0, "type": "base", "rmid": "DEF", "cmx": 1},
                            {"id": 1, "type": "bb", "rmid": "SHOP", "cmx": 100},
                            {"id": 4, "type": "ante", "rmid": "ANTE", "cmx": 1.3},
                        ]
                    }
                },
            ),
        ]
    )

    assert profile is not None
    assert profile.source == "client_json_bet_slots+legacy_bid_serializer"
    assert profile.catalog_complete is True
    assert profile.wire_complete is True
    assert profile.base_wire_complete is True
    assert profile.base_request_fields == {
        "bet": "$BASE_BET_STRING",
        "bid": 0,
    }
    assert [mode.mode_id for mode in profile.modes] == ["shop", "ante"]
    assert profile.modes[0].request_fields == {
        "bet": "$BASE_BET_STRING",
        "bid": 1,
        "purchased_feature": "buy_bonus",
    }
    assert profile.modes[1].request_fields == {
        "bet": "$BASE_BET_STRING",
        "bid": 4,
    }

def test_merges_disabled_buy_catalog_with_legacy_7rst_base_serializer():
    sources = [
        (
            "https://game.demo.bgaming-network.com/bs_lib/src/BS_lib.js",
            (
                "_bgCallRpcMethod mConnectUrl bet_type 'play' "
                "createEmptyObject freebet bet_slots "
                "eBetsIDs={'DEFAULT':0x0,'SHOP':0x1}"
            ),
        ),
        (
            "https://game.demo.bgaming-network.com/res/data/resdb/slot_parameters.json",
            {"bg_gaming": {"buy_btn": False}},
        ),
    ]

    profile = discover_hyperhive_static_sources(sources)

    assert profile is not None
    assert profile.source == "client_json_buy_disabled+legacy_rpc_manager"
    assert profile.catalog_complete is True
    assert profile.wire_complete is True
    assert profile.base_wire_complete is True
    assert profile.base_request_fields == {
        "bet": "$BASE_BET_STRING",
        "bid": 0,
    }
    assert profile.modes == ()

