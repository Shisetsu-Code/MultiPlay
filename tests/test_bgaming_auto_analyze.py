import json

from multiplay.models import EvidenceBundle, HttpExchange, ScriptEvidence
from multiplay.providers.bgaming.auto_analyze import (
    _merge_evidence,
    _require_runtime_identity,
    _write_safe_har,
)


def test_safe_contract_har_strips_query_and_redacts_loaded_shapes(tmp_path):
    primary = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="x",
                method="POST",
                url="https://demo.bgaming-network.com/api/Foo/12345/opaque-session?token=secret",
                request_headers={"cookie": "<redacted>"},
                request_body={
                    "command": "spin",
                    "options": {"bet": 100},
                    "token": "<redacted>",
                },
                response_status=200,
                response_body={"balance": 1000},
            )
        ],
        scripts=[
            ScriptEvidence(
                evidence_id="s",
                source="https://cdn.bgaming-network.com/app.js?token=secret",
                text='x={command:"spin"}',
            )
        ],
        metadata={"source": "primary"},
    )
    merged = _merge_evidence(primary, EvidenceBundle(metadata={"source": "secondary"}))
    path = tmp_path / "contract.har"
    _write_safe_har(merged, path)

    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)

    assert "?token=secret" not in raw
    assert "opaque-session" not in raw
    request_entry = payload["log"]["entries"][0]["request"]
    request_body = json.loads(request_entry["postData"]["text"])
    assert request_body["token"] == "<redacted>"
    assert request_entry["headers"][0]["value"] == "<redacted>"
    assert payload["log"]["entries"]


def test_merge_evidence_deduplicates_same_exchange():
    exchange = HttpExchange(
        evidence_id="a",
        method="POST",
        url="https://example.test/api",
        request_body={"command": "spin"},
        response_status=200,
        response_body={"ok": True},
    )
    merged = _merge_evidence(
        EvidenceBundle(http=[exchange]),
        EvidenceBundle(http=[exchange]),
    )
    assert len(merged.http) == 1



def test_runtime_identity_rejects_wrong_public_game():
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="x",
                method="POST",
                url=(
                    "https://demo.bgaming-network.com/api/"
                    "MagicMummyMegaways/123/session"
                ),
                request_body={"command": "init"},
                response_status=200,
            )
        ]
    )

    try:
        _require_runtime_identity(
            "https://bgaming.com/games/sweet-royale-megaways",
            evidence,
        )
    except ValueError as exc:
        assert "does not match requested public game" in str(exc)
    else:
        raise AssertionError("wrong embedded runtime must be rejected")


def test_runtime_identity_accepts_matching_public_game():
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="x",
                method="POST",
                url=(
                    "https://demo.bgaming-network.com/api/"
                    "SweetRoyaleMegaways/123/session"
                ),
                request_body={"command": "init"},
                response_status=200,
            )
        ]
    )

    _require_runtime_identity(
        "https://bgaming.com/games/sweet-royale-megaways",
        evidence,
    )
