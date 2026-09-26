from multiplay.analyzer import MultiProtocolAnalyzer
from multiplay.models import EvidenceBundle, HttpExchange
from multiplay.providers.bgaming import BGamingProviderAdapter


def _exchange(eid, method, url, request, response):
    return HttpExchange(
        evidence_id=eid,
        method=method,
        url=url,
        request_body=request,
        response_status=200,
        response_body=response,
    )


def test_bgaming_ledger_normalizes_command_and_switch_endpoint():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "spin",
                "POST",
                "https://demo.bgaming-network.com/api/Foo/12345/session-value",
                {
                    "command": "spin",
                    "options": {"bet": 100},
                    "extra_data": {"round_series_id": 123},
                },
                {
                    "options": {"bets": [100]},
                    "flow": {"state": "closed", "available_actions": ["spin"]},
                    "balance": 900,
                },
            ),
            _exchange(
                "switch",
                "GET",
                "https://demo.bgaming-network.com/lobby/switch?game=Foo2&from=Foo",
                None,
                {
                    "identifier": "Foo2",
                    "api": "https://demo.bgaming-network.com/api/Foo2/12345/session-2",
                    "csrfTokenHeaderName": "X-CSRF",
                    "csrfTokenHeaderValue": "secret",
                },
            ),
        ]
    )
    analysis = MultiProtocolAnalyzer().analyze(evidence, provider="bgaming")

    records = BGamingProviderAdapter().endpoint_records(
        evidence,
        analysis,
        source_ref="fixture:bgaming",
        environment="demo",
    )

    spin = next(item for item in records if item.action == "spin")
    switch = next(item for item in records if item.action == "switch_variant")

    assert "provider_family=api-v2" in spin.notes
    assert spin.endpoint_template.endswith("/api/Foo/<id>/<session>")
    assert "session-value" not in spin.endpoint_template
    assert switch.request_format == {
        "query": {
            "from": "<dynamic:from>",
            "game": "<dynamic:game>",
        }
    }
    assert switch.live_state.value == "UNKNOWN"


def test_hyperhive_ledger_keeps_replay_requirements():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "play",
                "POST",
                "https://demo.bgaming-network.com/api",
                {
                    "id": 0,
                    "jsonrpc": "2.0",
                    "method": "play",
                    "params": {
                        "token": "secret",
                        "req": {"bet": "1.00", "bet_type": "bet"},
                        "state_lock": "",
                    },
                },
                {"jsonrpc": "2.0", "id": 0, "result": {"final": True}},
            )
        ]
    )
    analysis = MultiProtocolAnalyzer().analyze(evidence, provider="bgaming")
    records = BGamingProviderAdapter().endpoint_records(
        evidence,
        analysis,
        source_ref="fixture:hyperhive",
        environment="demo",
    )

    play = next(item for item in records if item.action == "rpc:play")
    assert "provider_family=hyperhive-jsonrpc" in play.notes
    assert play.request_format["params"]["token"] == "<redacted>"
    assert play.request_format["params"]["req"]["bet"] == "<dynamic:bet>"
    assert play.request_format["params"]["req"]["bet_type"] == "bet"
    assert "$.params.req.bet_type" not in play.dynamic_fields


def test_legacy_spin_ledger_keeps_family_and_dynamic_line_bets():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "init",
                "POST",
                "https://demo.bgaming-network.com/api/Catdiana/12345/session",
                {"command": "init", "extra_data": {"round_series_id": 1}},
                {
                    "options": {"line_bets": [1, 2], "lines": [[0], [1], [2]]},
                    "game": {"state": "closed"},
                    "balance": 100,
                    "available_commands": ["spin"],
                },
            ),
            _exchange(
                "spin",
                "POST",
                "https://demo.bgaming-network.com/api/Catdiana/12345/session",
                {
                    "command": "spin",
                    "options": {"bets": {"0": 1, "1": 1, "2": 1}},
                    "extra_data": {"round_series_id": 1, "client_seed": 42},
                },
                {
                    "bets": {"lines": {"0": 1, "1": 1, "2": 1}},
                    "game": {"state": "closed", "action": "spin"},
                    "balance": 99,
                    "available_commands": ["spin"],
                },
            ),
        ]
    )
    analysis = MultiProtocolAnalyzer().analyze(evidence, provider="bgaming")
    records = BGamingProviderAdapter().endpoint_records(
        evidence,
        analysis,
        source_ref="fixture:legacy",
        environment="demo",
    )

    spin = next(item for item in records if item.action == "spin")
    assert "provider_family=legacy-lines" in spin.notes
    assert spin.request_format["options"]["bets"] == {
        "0": "<dynamic:line_bet>",
        "1": "<dynamic:line_bet>",
        "2": "<dynamic:line_bet>",
    }
    assert spin.request_format["extra_data"]["client_seed"] == "<dynamic:client_seed>"


def test_hyperhive_ledger_keeps_observed_play_variants_separate():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "base",
                "POST",
                "https://demo.bgaming-network.com/api/api",
                {
                    "id": "a",
                    "jsonrpc": "2.0",
                    "method": "play",
                    "params": {
                        "token": "secret",
                        "req": {"bet": 100, "bet_type": "bet"},
                    },
                },
                {"jsonrpc": "2.0", "id": "a", "result": {"final": True}},
            ),
            _exchange(
                "purchase",
                "POST",
                "https://demo.bgaming-network.com/api/api",
                {
                    "id": "b",
                    "jsonrpc": "2.0",
                    "method": "play",
                    "params": {
                        "token": "secret",
                        "req": {
                            "bet": 100,
                            "bet_type": "bet",
                            "purchased_feature": "buy_bonus",
                            "custom_req": {
                                "action": "spin",
                                "exponent": 2,
                                "stake": 100,
                                "isNormalBuy": True,
                            },
                        },
                    },
                },
                {"jsonrpc": "2.0", "id": "b", "result": {"final": True}},
            ),
        ]
    )
    analysis = MultiProtocolAnalyzer().analyze(evidence, provider="bgaming")
    records = BGamingProviderAdapter().endpoint_records(
        evidence,
        analysis,
        source_ref="fixture:hyperhive-variants",
        environment="demo",
    )

    base = next(item for item in records if item.action == "rpc:play:base")
    purchase = next(
        item
        for item in records
        if item.action.startswith("rpc:play:variant-")
    )

    assert base.protocol_family == "hyperhive-jsonrpc"
    assert purchase.protocol_family == "hyperhive-jsonrpc"
    assert purchase.request_format["params"]["req"]["purchased_feature"] == "buy_bonus"
    assert purchase.request_format["params"]["req"]["custom_req"]["action"] == "spin"
    assert purchase.request_format["params"]["req"]["custom_req"]["stake"] == "<dynamic:stake>"
    assert any("purchased_feature" in note for note in purchase.notes)



def test_bgaming_ledger_excludes_telemetry_posts():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "spin",
                "POST",
                "https://demo.bgaming-network.com/api/Foo/12345/session",
                {
                    "command": "spin",
                    "options": {"bet": 100},
                    "extra_data": {"round_series_id": 1},
                },
                {
                    "options": {"bets": [100]},
                    "flow": {"state": "closed", "available_actions": ["spin"]},
                    "balance": 900,
                },
            ),
            _exchange(
                "rum",
                "POST",
                "https://demo.bgaming-network.com/cdn-cgi/rum",
                {"type": "rum"},
                {"ok": True},
            ),
            _exchange(
                "analytics",
                "POST",
                "https://analytics.google.com/g/collect",
                {"event": "page"},
                {"ok": True},
            ),
        ]
    )

    analysis = MultiProtocolAnalyzer().analyze(evidence, provider="bgaming")
    records = BGamingProviderAdapter().endpoint_records(
        evidence,
        analysis,
        source_ref="fixture:telemetry",
        environment="demo",
    )

    assert any(item.action == "spin" for item in records)
    assert all("analytics.google.com" not in item.endpoint_template for item in records)
    assert all("/cdn-cgi/rum" not in item.endpoint_template for item in records)



def test_switchable_ledger_accepts_causal_child_init_without_response_body():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "parent-init",
                "POST",
                "https://demo.bgaming-network.com/api/Container/12345/session",
                {
                    "command": "init",
                    "extra_data": {"round_series_id": 1},
                },
                {"wallet": 1000, "game": 0},
            ),
            HttpExchange(
                evidence_id="switch",
                method="GET",
                url=(
                    "https://demo.bgaming-network.com/lobby/FUN/session/launch"
                    "?game=Child100&from=Container"
                ),
                response_status=200,
                response_body=None,
            ),
            _exchange(
                "child-init",
                "POST",
                "https://demo.bgaming-network.com/api/Child100/67890/child-session",
                {
                    "command": "init",
                    "extra_data": {"round_series_id": 2},
                },
                {
                    "options": {"bets": [1]},
                    "flow": {"state": "closed", "available_actions": ["spin"]},
                },
            ),
        ]
    )
    analysis = MultiProtocolAnalyzer().analyze(evidence, provider="bgaming")
    records = BGamingProviderAdapter().endpoint_records(
        evidence,
        analysis,
        source_ref="fixture:switch-causal",
        environment="demo",
    )

    switch = next(item for item in records if item.action == "switch_variant")
    assert switch.protocol_family == "switchable-container"
    assert switch.request_format == {
        "query": {
            "from": "<dynamic:from>",
            "game": "<dynamic:game>",
        }
    }
    assert switch.response_format is None
    assert any("selected child init" in note for note in switch.notes)
