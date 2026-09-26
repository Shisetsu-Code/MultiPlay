from multiplay.models import EvidenceBundle, HttpExchange, ProtocolContract, ScriptEvidence
from multiplay.providers.bgaming import BGamingProviderAdapter
from multiplay.providers.bgaming.client_contracts import discover_client_action_contracts


def _evidence(script):
    return EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="spin",
                method="POST",
                url="https://demo.bgaming-network.com/api/Foo/12345/session",
                request_body={
                    "command": "spin",
                    "options": {"bet": 100},
                    "extra_data": {"round_series_id": 1},
                },
                response_status=200,
                response_body={
                    "options": {"bets": [100]},
                    "flow": {
                        "state": "pick",
                        "available_actions": ["pick_cards"],
                    },
                },
            )
        ],
        scripts=[ScriptEvidence("bundle", "bundle.js", script)],
    )


def test_discovers_literal_action_variant_without_action_allowlist():
    evidence = _evidence(
        'send({command:"pick_cards",options:{mode:"any",index:0}})'
    )
    contracts = discover_client_action_contracts(evidence)
    contract = contracts["pick_cards"]

    assert contract.shape_proven is True
    assert contract.replay_eligible is True
    assert contract.option_fields == ["mode", "index"]
    assert contract.variants[0].options == {"mode": "any", "index": 0}


def test_dynamic_client_field_stays_unresolved():
    evidence = _evidence(
        'send({command:"pick_cards",options:{mode:"any",index:i}})'
    )
    contract = discover_client_action_contracts(evidence)["pick_cards"]

    assert contract.shape_proven is True
    assert contract.replay_eligible is False
    assert contract.unresolved_fields == ["index"]


def test_adapter_reports_client_proven_unknown_action_separately():
    evidence = _evidence(
        'send({command:"pick_cards",options:{mode:"any",index:0}})'
    )
    reasons = BGamingProviderAdapter().validate(
        evidence,
        [ProtocolContract("http-command")],
    )

    assert any(
        "pick_cards" in reason and "client serializer" in reason
        for reason in reasons
    )
