from multiplay.analyzer import MultiProtocolAnalyzer
from multiplay.models import EvidenceBundle, HttpExchange


def _exchange(eid, body, response):
    return HttpExchange(
        evidence_id=eid,
        method="POST",
        url="https://example.test/api",
        request_body=body,
        response_status=200,
        response_body=response,
    )


def test_jsonrpc_only_is_not_double_classified_as_http_command():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "rpc",
                {"jsonrpc": "2.0", "id": 1, "method": "play", "params": {"token": "x"}},
                {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
            )
        ]
    )

    result = MultiProtocolAnalyzer().analyze(evidence, provider="bgaming")

    assert [contract.family for contract in result.contracts] == ["jsonrpc-2.0"]


def test_multiple_protocol_families_can_coexist():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "rpc",
                {"jsonrpc": "2.0", "id": 1, "method": "init", "params": {}},
                {"jsonrpc": "2.0", "id": 1, "result": {}},
            ),
            _exchange(
                "cmd",
                {"command": "spin", "bet": "1"},
                {"balance": 99, "result": {"final": True}},
            ),
        ]
    )

    result = MultiProtocolAnalyzer().analyze(evidence)

    families = {contract.family for contract in result.contracts}
    assert families == {"jsonrpc-2.0", "http-command"}
