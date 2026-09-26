from multiplay.models import EvidenceBundle, HttpExchange
from multiplay.providers.bgaming.capabilities import (
    hyperhive_init_capabilities,
    hyperhive_purchase_coverage,
)


def test_hyperhive_init_capabilities_detects_protocol_domain():
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
    assert result["purchased_feature_domain_present"] is True
    assert result["purchased_feature_domain_count"] == 2
    assert result["purchased_feature_domain_shape"] == "list"
    assert result["purchased_feature_domain"] == [
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
    assert result["purchased_feature_domain_present"] is False
    assert result["purchased_feature_domain_count"] == 0



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
    assert result["purchased_feature_domain"] == [
        {
            "name": "buy_bonus",
            "feature_token": "<redacted>",
        }
    ]



def test_hyperhive_purchase_coverage_reports_missing_variants():
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
                            "purchased_features": ["buy_bonus", "super_bonus"],
                        }
                    }
                },
            ),
            HttpExchange(
                evidence_id="buy",
                method="POST",
                url="https://example.test/api",
                request_body={
                    "jsonrpc": "2.0",
                    "method": "play",
                    "id": 1,
                    "params": {
                        "token": "<redacted>",
                        "req": {
                            "bet": 100,
                            "purchased_feature": "buy_bonus",
                        },
                    },
                },
                response_status=200,
                response_body={"result": {"final": True}},
            ),
        ]
    )

    coverage = hyperhive_purchase_coverage(evidence)
    assert coverage["advertised"] == ["buy_bonus", "super_bonus"]
    assert coverage["observed"] == ["buy_bonus"]
    assert coverage["missing"] == ["super_bonus"]
    assert coverage["complete"] is False
