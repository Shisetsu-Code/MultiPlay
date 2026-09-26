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
    assert spin.endpoint_template.endswith("/api/Foo/<id>/session-value")
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
