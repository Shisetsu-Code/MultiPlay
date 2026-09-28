from multiplay.models import EvidenceBundle, HttpExchange, ScriptEvidence
from multiplay.providers.bgaming.hyperhive_static import (
    extract_hyperhive_static_profile,
    seed_hyperhive_static_routes,
)


def _scripts(*items: tuple[str, str]) -> EvidenceBundle:
    return EvidenceBundle(
        scripts=[
            ScriptEvidence(evidence_id=f"s{index}", source=url, text=text)
            for index, (url, text) in enumerate(items)
        ]
    )


def test_recycle_riches_recovers_validated_purchase_wires():
    source = (
        'const purchaseFeaturesConfig=['
        '{id:"chance",type:"buy_chance",betPriceMultiplier:1.4,configFeatureType:1},'
        '{id:"buy_random",type:"buy_bonus",betPriceMultiplier:80,configFeatureType:1},'
        '{id:"buy_max",type:"buy_bonus",betPriceMultiplier:160,configFeatureType:1}'
        '];'
    )
    evidence = _scripts(("https://cdn.test/recycle-riches.game.js", source))

    profile = extract_hyperhive_static_profile(evidence)

    assert profile.catalog_complete is True
    assert profile.wire_complete is True
    assert [mode.mode_id for mode in profile.modes] == ["chance", "buy_random", "buy_max"]
    assert profile.modes[0].request_fields == {
        "purchased_feature": "buy_chance",
        "custom_field": "chance",
    }
    assert profile.modes[1].request_fields == {
        "purchased_feature": "buy_bonus",
        "custom_field": "buy_random",
    }


def test_sweet_samurai_keeps_catalog_but_does_not_invent_wire():
    source = (
        'const BUY_BONUS_COSTS={DEEP_SPIN:100,DEEP_BONANZA:150};'
        'const DEEP_SPIN="deep_spin",DEEP_BONANZA="deep_bonanza";'
    )
    evidence = _scripts(("https://cdn.test/sweet-samurai.game.js", source))

    profile = extract_hyperhive_static_profile(evidence)

    assert profile.catalog_complete is True
    assert profile.wire_complete is False
    assert [(mode.mode_id, mode.multiplier) for mode in profile.modes] == [
        ("deep_spin", 100.0),
        ("deep_bonanza", 150.0),
    ]
    assert all(mode.request_fields is None for mode in profile.modes)
    assert all(mode.wire_complete is False for mode in profile.modes)


def test_grand_patron_reads_bet_slots_from_json_response():
    payload = {
        "bet_slots": [
            {"id": 0, "type": "base", "rmid": "DEF", "cmx": 1, "tb": 20},
            {"id": 1, "type": "bb", "rmid": "SHOP", "cmx": 100, "tb": 20},
            {"id": 2, "type": "bb", "rmid": "SHOP2", "cmx": 250, "tb": 20},
            {"id": 3, "type": "bb", "rmid": "SHOP3", "cmx": 1000, "tb": 20},
            {
                "id": 4,
                "type": "ante",
                "rmid": "ANTE",
                "cmx": 1.3,
                "tb": 20,
                "tbvs": [20, 40, 100],
            },
        ]
    }
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="bets",
                method="GET",
                url="https://cdn.test/bets_data.json",
                response_status=200,
                response_body=payload,
            )
        ]
    )

    profile = extract_hyperhive_static_profile(evidence)

    assert profile.source == "client_json_bet_slots"
    assert profile.catalog_complete is True
    assert profile.wire_complete is False
    assert [(mode.mode_id, mode.multiplier) for mode in profile.modes] == [
        ("shop", 100.0),
        ("shop2", 250.0),
        ("shop3", 1000.0),
        ("ante", 1.3),
    ]
    assert profile.modes[-1].raw_bets == (20.0, 40.0, 100.0)
    assert profile.modes[-1].wire_requirements == ("round_mode_id",)


def test_star_trek_definition_is_resolved_by_client_feature_flags():
    definitions = {
        "engine": {
            "definition": {
                "featureBuyMulFreespin": 75,
                "featureBuyMulRespin": 30,
            }
        }
    }
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="definitions",
                method="GET",
                url="https://cdn.test/definitions.json",
                response_status=200,
                response_body=definitions,
            )
        ],
        scripts=[
            ScriptEvidence(
                evidence_id="client",
                source="https://cdn.test/client.min.js",
                text=(
                    "customizeFeatureBuyRequestData();"
                    "x.isFeatureBuyFreeSpin=true;"
                    "x.isFeatureBuyRespin=false;"
                ),
            )
        ],
    )

    profile = extract_hyperhive_static_profile(evidence)

    assert profile.source == "client_static_feature_buy_flags"
    assert profile.wire_complete is True
    assert [(mode.mode_id, mode.multiplier) for mode in profile.modes] == [
        ("freespin", 75.0),
        ("respin", 30.0),
    ]
    free = profile.modes[0].request_fields
    assert free is not None
    assert free["purchased_feature"] == "buy_bonus"
    assert free["custom_req"]["isFeatureBuyFreeSpin"] is True
    assert free["custom_req"]["isFeatureBuyRespin"] is False


def test_blazing_firepots_recovers_chance_and_buy_modes():
    source = (
        'a={purchased_feature:"buy_bonus",bet_type:"betting"};'
        'b={purchased_feature:"buy_chance",bet_type:"betting"};'
        'formatMoney(100*currentBet);'
        'const shown=isAnteSpinActive?1.4*currentBet:currentBet;'
    )
    profile = extract_hyperhive_static_profile(
        _scripts(("https://cdn.test/blazing.js", source))
    )

    assert profile.wire_complete is True
    assert [(mode.feature, mode.multiplier) for mode in profile.modes] == [
        ("buy_chance", 1.4),
        ("buy_bonus", 100.0),
    ]
    assert all(mode.request_fields["bet_type"] == "betting" for mode in profile.modes)


def test_jungle_queen_recovers_fixed_buybonus_wire():
    source = (
        'const ua=100;const a="buybonus",b="buybonus";'
        'send({action:a,id:b,purchased_feature:"buy_bonus"});'
    )
    profile = extract_hyperhive_static_profile(
        _scripts(("https://cdn.test/jungle.js", source))
    )

    assert profile.source == "client_static_jungle_buy"
    assert profile.modes[0].request_fields == {
        "action": "buybonus",
        "id": "buybonus",
        "purchased_feature": "buy_bonus",
    }


def test_static_route_seeding_replaces_ambiguous_generic_buy_route():
    profile = extract_hyperhive_static_profile(
        _scripts(
            (
                "https://cdn.test/sweet-samurai.game.js",
                'const BUY_BONUS_COSTS={DEEP_SPIN:100,DEEP_BONANZA:150};'
                'const DEEP_SPIN="deep_spin",DEEP_BONANZA="deep_bonanza";',
            )
        )
    )
    routes = [
        {
            "route_id": "generic-buy",
            "semantic": "BUY_BONUS",
            "status": "NETWORK_INFERRED",
            "interface_role": "network_action",
            "wire_markers": ["method=play"],
        }
    ]

    seed_hyperhive_static_routes(routes, profile)

    assert routes[0]["interface_role"] == "client_control"
    static = [route for route in routes if str(route["route_id"]).startswith("static:")]
    assert len(static) == 2
    assert all(route["status"] == "CLIENT_DECLARED_WIRE_UNRESOLVED" for route in static)
    assert all(route["direct_executable"] is False for route in static)


def test_plain_spin_only_profile_closes_false_purchase_capability():
    source = (
        'network.invoke("play",{req:{bet:100,bet_type:"bet",'
        'custom_field:"custom_value",fe_exponent:2}});'
    )
    profile = extract_hyperhive_static_profile(
        _scripts(("https://cdn.test/game.min.js", source))
    )

    assert profile.source == "client_static_plain_spin_only"
    assert profile.catalog_complete is True
    assert profile.wire_complete is True
    assert profile.modes == ()
