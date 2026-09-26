from multiplay.models import EvidenceBundle, HttpExchange, ProtocolContract, ScriptEvidence
from multiplay.providers.bgaming import (
    API_V2,
    HYPERHIVE_JSONRPC,
    LEGACY_LINES,
    BGamingProviderAdapter,
    classify_bgaming,
)


def _http(eid, body, response, *, url="https://demo.bgaming-network.com/api"):
    return HttpExchange(
        evidence_id=eid,
        method="POST",
        url=url,
        request_body=body,
        response_status=200,
        response_body=response,
    )


def test_classifies_api_v2_without_game_title():
    evidence = EvidenceBundle(
        http=[
            _http(
                "spin",
                {
                    "command": "spin",
                    "options": {"bet": 100},
                    "extra_data": {"round_series_id": 1},
                },
                {
                    "options": {"bets": [100]},
                    "flow": {"state": "closed", "available_actions": ["spin"]},
                    "outcome": {"bet": 100, "win": 0},
                    "balance": 9900,
                },
                url="https://demo.bgaming-network.com/api/Foo/12345/session-value",
            )
        ]
    )

    families = {item.family for item in classify_bgaming(evidence)}
    assert API_V2 in families

    adapter = BGamingProviderAdapter()
    assert adapter.validate(evidence, [ProtocolContract("http-command")]) == []


def test_api_v2_advertised_choice_requires_demonstrated_wire():
    evidence = EvidenceBundle(
        http=[
            _http(
                "spin",
                {
                    "command": "spin",
                    "options": {"bet": 100},
                    "extra_data": {"round_series_id": 1},
                },
                {
                    "options": {"bets": [100]},
                    "flow": {
                        "state": "select_bonus",
                        "available_actions": ["select_bonus"],
                    },
                    "game": {
                        "freespin_params": {
                            "variants": [{"name": "a"}, {"name": "b"}]
                        }
                    },
                },
            )
        ]
    )

    reasons = BGamingProviderAdapter().validate(evidence, [ProtocolContract("http-command")])
    assert any("select_bonus" in reason and "not demonstrated" in reason for reason in reasons)


def test_classifies_legacy_lines_and_requires_full_line_mapping():
    evidence = EvidenceBundle(
        http=[
            _http(
                "init",
                {
                    "command": "init",
                    "extra_data": {"round_series_id": 1},
                },
                {
                    "options": {
                        "line_bets": [1, 2],
                        "lines": [[0, 0], [1, 1], [2, 2]],
                    }
                },
            ),
            _http(
                "spin",
                {
                    "command": "spin",
                    "options": {"bets": {"0": 1, "1": 1, "2": 1}},
                    "extra_data": {"round_series_id": 1},
                },
                {"bets": {"lines": {"0": 1, "1": 1, "2": 1}}, "game": {"state": "closed"}},
            ),
        ]
    )

    families = {item.family for item in classify_bgaming(evidence)}
    assert LEGACY_LINES in families
    reasons = BGamingProviderAdapter().validate(evidence, [ProtocolContract("http-command")])
    assert not any(reason.startswith("legacy-lines:") for reason in reasons)


def test_hyperhive_preserves_exact_play_envelope_as_validation_input():
    evidence = EvidenceBundle(
        http=[
            _http(
                "init",
                {
                    "id": 0,
                    "jsonrpc": "2.0",
                    "method": "init",
                    "params": {"token": "fresh"},
                },
                {"jsonrpc": "2.0", "id": 0, "result": {}},
            ),
            _http(
                "play",
                {
                    "id": 0,
                    "jsonrpc": "2.0",
                    "method": "play",
                    "params": {
                        "token": "fresh",
                        "req": {
                            "bet": "1.00",
                            "bet_type": "bet",
                            "custom_req": {
                                "action": "spin",
                                "exponent": 2,
                                "stake": "1.00",
                            },
                        },
                        "state_lock": "",
                    },
                },
                {"jsonrpc": "2.0", "id": 0, "result": {"final": True}},
            ),
        ]
    )

    families = {item.family for item in classify_bgaming(evidence)}
    assert HYPERHIVE_JSONRPC in families
    assert BGamingProviderAdapter().validate(
        evidence,
        [ProtocolContract("jsonrpc-2.0")],
    ) == []


def test_hyperhive_script_purchase_literal_is_not_executable_proof():
    evidence = EvidenceBundle(
        http=[
            _http(
                "init",
                {
                    "id": 0,
                    "jsonrpc": "2.0",
                    "method": "init",
                    "params": {"token": "fresh"},
                },
                {"result": {}},
            ),
            _http(
                "play",
                {
                    "id": 0,
                    "jsonrpc": "2.0",
                    "method": "play",
                    "params": {"token": "fresh", "req": {"bet": 100}, "state_lock": ""},
                },
                {"result": {"final": True}},
            ),
        ],
        scripts=[
            ScriptEvidence("script", "bundle.js", 'purchased_feature="buy_bonus"')
        ],
    )

    reasons = BGamingProviderAdapter().validate(
        evidence,
        [ProtocolContract("jsonrpc-2.0")],
    )
    assert any("purchase wire" in reason for reason in reasons)
