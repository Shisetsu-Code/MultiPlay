import json

from multiplay.endpoints import ProviderKnowledgeStore
from multiplay.models import (
    AnalysisResult,
    AnalysisStatus,
    EvidenceBundle,
    HttpExchange,
    ProtocolContract,
    ProtocolTransition,
    Transport,
)


def _analysis():
    return AnalysisResult(
        status=AnalysisStatus.WIRE_COMPLETE,
        provider="bgaming",
        contracts=[
            ProtocolContract(
                family="jsonrpc-2.0",
                transitions=[
                    ProtocolTransition(
                        name="play",
                        family="jsonrpc-2.0",
                        transport=Transport.HTTP,
                        endpoint_template=(
                            "https://example.test/api/Game/12345/"
                            "123e4567-e89b-12d3-a456-426614174000?token=secret"
                        ),
                        method="POST",
                        action="play",
                        request_keys=("bet", "token"),
                        response_keys=("result",),
                        evidence_ids=("e1",),
                        deterministic=True,
                    )
                ],
            )
        ],
    )


def test_endpoint_ledger_redacts_sensitive_and_dynamic_values(tmp_path):
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="e1",
                method="POST",
                url="https://example.test/api",
                request_body={
                    "token": "SUPER_SECRET",
                    "bet": "5.00",
                    "purchased_feature": "buy_bonus",
                },
                response_status=200,
                response_body={"result": {"final": True}, "balance": 95},
            )
        ]
    )

    store = ProviderKnowledgeStore(tmp_path)
    store.record_analysis(
        provider="bgaming",
        analysis=_analysis(),
        evidence=evidence,
        source_ref="fixture:bgaming",
    )

    data = json.loads((tmp_path / "bgaming" / "endpoints.json").read_text())
    endpoint = data[0]
    serialized = json.dumps(endpoint)

    assert "SUPER_SECRET" not in serialized
    assert "token=secret" not in serialized
    assert endpoint["request_format"]["token"] == "<redacted>"
    assert endpoint["request_format"]["bet"] == "<dynamic:bet>"
    assert endpoint["request_format"]["purchased_feature"] == "buy_bonus"


def test_finalize_requires_endpoint_ledger(tmp_path):
    store = ProviderKnowledgeStore(tmp_path)

    try:
        store.finalize_provider(provider="unknown")
    except ValueError as exc:
        assert "no endpoint ledger" in str(exc)
    else:
        raise AssertionError("expected ValueError")
