from __future__ import annotations

from multiplay.models import EvidenceBundle, HttpExchange
from multiplay.pipeline import analyze_evidence
from multiplay.providers.yggdrasil import YggdrasilProviderAdapter


def _play(evidence_id: str, *, command: str, amount: str) -> HttpExchange:
    return HttpExchange(
        evidence_id=evidence_id,
        method="POST",
        url="https://demo.yggdrasilgaming.com/game.web/service?fn=play",
        request_body={
            "channel": "pc",
            "currency": "EUR",
            "lang": "en",
            "gameid": "10964",
            "gameHistorySessionId": "session-secret",
            "gameHistoryTicketId": "ticket-secret",
            "amount": amount,
            "coin": "0.1",
            "cmd": command,
            "clientinfo": "dynamic-client-id",
        },
        response_status=200,
        response_body={"ok": True},
    )


def test_yggdrasil_purchase_variants_are_provider_recognized_but_not_base_spin():
    evidence = EvidenceBundle(
        http=[
            _play("buy-high", command="BB_5", amount="390"),
            _play("buy-low", command="BB_2", amount="65"),
        ]
    )

    result = analyze_evidence(evidence, provider="yggdrasil")

    assert result.provider_decision is not None
    assert result.provider_decision.recognized is True
    assert result.provider_decision.confidence >= 0.99
    assert result.analysis.status.value == "PARTIAL_REQUIRES_REVIEW"
    assert result.provider_blockers == [
        "yggdrasil: purchase wire is demonstrated, but base spin/play command "
        "is not demonstrated by current evidence."
    ]

    actions = {
        transition.action
        for contract in result.analysis.contracts
        for transition in contract.transitions
        if transition.endpoint_template.endswith("/game.web/service")
    }
    assert actions == {"cmd=BB_2", "cmd=BB_5"}


def test_yggdrasil_endpoint_records_keep_purchase_variants_separate_and_redact_session():
    evidence = EvidenceBundle(
        http=[
            _play("buy-high", command="BB_5", amount="390"),
            _play("buy-low", command="BB_2", amount="65"),
        ]
    )
    result = analyze_evidence(evidence, provider="yggdrasil")
    assert result.provider_adapter is not None

    records = result.provider_adapter.endpoint_records(
        evidence,
        result.analysis,
        source_ref="fixture:yggdrasil-two-purchases",
        environment="demo",
    )

    assert {record.action for record in records} == {"BB_2", "BB_5"}
    assert all(
        record.endpoint_template
        == "https://demo.yggdrasilgaming.com/game.web/service?fn=play"
        for record in records
    )
    assert all(
        record.request_format["gameHistorySessionId"] == "<redacted>"
        and record.request_format["gameHistoryTicketId"] == "<redacted>"
        for record in records
    )
    assert all(
        record.request_format["amount"] == "<dynamic:amount>"
        and record.request_format["gameid"] == "<dynamic:gameid>"
        for record in records
    )
    assert all("$.gameHistorySessionId" in record.sensitive_fields for record in records)


def test_yggdrasil_adapter_ignores_analytics_post():
    evidence = EvidenceBundle(
        http=[
            _play("buy", command="BB_2", amount="65"),
            HttpExchange(
                evidence_id="analytics",
                method="POST",
                url="https://www.google-analytics.com/g/collect",
                request_body={"event": "custom_wager_open"},
                response_status=204,
                response_body="",
            ),
        ]
    )

    adapter = YggdrasilProviderAdapter()
    decision = adapter.recognize(evidence, [])
    assert decision.recognized is True

    records = adapter.endpoint_records(
        evidence,
        analyze_evidence(evidence).analysis,
        source_ref="fixture:telemetry-filter",
        environment="demo",
    )
    assert len(records) == 1
    assert records[0].action == "BB_2"
