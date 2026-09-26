from multiplay.models import EvidenceBundle, HttpExchange
from multiplay.providers.bgaming.capabilities import hyperhive_init_capabilities


def test_hyperhive_init_capabilities_detects_purchases():
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="init",
                method="POST",
                url="https://example.test/api",
                request_body={
                    "jsonrpc": "2.0",
                    "method": "init",
                    "id": 0,
                    "params": {"token": "<redacted>", "req": {"action": "INIT"}},
                },
                response_status=200,
                response_body={
                    "jsonrpc": "2.0",
                    "id": 0,
                    "result": {
                        "config": {
                            "default_bet": 100,
                            "bet_limits": [100, 200],
                            "purchased_features": [
                                {"name": "buy_bonus"},
                                {"name": "super_bonus"},
                            ],
                        }
                    },
                },
            )
        ]
    )

    result = hyperhive_init_capabilities(evidence)
    assert result["init_observed"] is True
    assert result["has_purchases"] is True
    assert result["purchase_count"] == 2
    assert result["purchased_features_shape"] == "list"
    assert result["purchased_features"] == [
        {"name": "buy_bonus"},
        {"name": "super_bonus"},
    ]


def test_hyperhive_init_capabilities_empty_purchase_domain():
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="init",
                method="POST",
                url="https://example.test/api",
                request_body={
                    "jsonrpc": "2.0",
                    "method": "init",
                    "id": 0,
                    "params": {"token": "<redacted>"},
                },
                response_status=200,
                response_body={
                    "jsonrpc": "2.0",
                    "id": 0,
                    "result": {
                        "config": {
                            "default_bet": 100,
                            "purchased_features": [],
                        }
                    },
                },
            )
        ]
    )

    result = hyperhive_init_capabilities(evidence)
    assert result["has_purchases"] is False
    assert result["purchase_count"] == 0



def test_hyperhive_capabilities_redacts_sensitive_purchase_fields():
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="init",
                method="POST",
                url="https://example.test/api",
                request_body={
                    "jsonrpc": "2.0",
                    "method": "init",
                    "id": 0,
                    "params": {"token": "<redacted>"},
                },
                response_status=200,
                response_body={
                    "result": {
                        "config": {
                            "purchased_features": [
                                {
                                    "name": "buy_bonus",
                                    "feature_token": "secret-value",
                                }
                            ]
                        }
                    }
                },
            )
        ]
    )

    result = hyperhive_init_capabilities(evidence)
    assert result["purchased_features"] == [
        {
            "name": "buy_bonus",
            "feature_token": "<redacted>",
        }
    ]
