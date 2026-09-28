import json

import multiplay.providers.bgaming.auto_analyze as auto_module
from multiplay.models import EvidenceBundle, HttpExchange, ScriptEvidence
from multiplay.providers.bgaming.auto_analyze import (
    _api_v2_declared_feature_rows,
    _api_v2_static_buy_features,
    _merge_evidence,
    _require_runtime_identity,
    _seed_api_v2_buy_feature_routes,
    _select_base_spin_browser_fallback,
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



def test_public_game_without_matching_demo_returns_partial(
    tmp_path,
    monkeypatch,
):
    public = "https://bgaming.com/games/sweet-royale-megaways"
    monkeypatch.setattr(
        auto_module,
        "resolve_catalog_execution_url",
        lambda *_args, **_kwargs: public,
    )

    def fail_probe(*_args, **_kwargs):
        raise ValueError("mismatched runtime")

    monkeypatch.setattr(auto_module, "probe_bgaming_demo", fail_probe)

    def must_not_capture(**_kwargs):
        raise AssertionError("browser must not open for unresolved public demo")

    monkeypatch.setattr(auto_module, "capture_browser_evidence", must_not_capture)

    report = auto_module.analyze_bgaming_demo(
        public,
        output_dir=tmp_path,
        screenshot=False,
    )

    assert report["status"] == "PARTIAL_REQUIRES_REVIEW"
    assert report["runtime_status"] == "NO_RESOLVABLE_DEMO"
    assert report["family"] == "unresolved"
    assert report["route_count"] == 0
    assert report["execution_url"] == ""
    assert (tmp_path / "analysis.json").exists()
    assert (tmp_path / "actions.json").exists()
    assert (tmp_path / "contract.har").exists()



def test_select_base_spin_browser_fallback_uses_explicit_client_control():
    routes = [
        {
            "route_id": "bonus",
            "semantic": "BUY_BONUS",
            "status": "NETWORK_INFERRED",
            "interface_role": "network_action",
            "control": "buy-btn",
            "handler": "currentScene.buyBonusClick\u00602",
        },
        {
            "route_id": "spin",
            "semantic": "SPIN",
            "status": "CLIENT_OR_UNKNOWN",
            "interface_role": "client_control",
            "control": "spin-button",
            "handler": "currentScene.spin\u00601",
            "confidence": "HIGH",
        },
    ]

    selected = _select_base_spin_browser_fallback(routes)

    assert selected is not None
    assert selected["route_id"] == "spin"

def test_static_buy_feature_table_enriches_matching_popup_controls():
    evidence = EvidenceBundle(
        scripts=[
            ScriptEvidence(
                evidence_id="s",
                source="https://example.test/app.js",
                text=(
                    'cfg={buy_features:{features:['
                    '{requestName:"freespin_buy",name:"bonus_1",level:"0",price:100},'
                    '{requestName:"freespin_buy",name:"bonus_2",level:"1",price:250}'
                    ']}};'
                ),
            )
        ]
    )
    assert _api_v2_static_buy_features(evidence) == [
        {"name": "bonus_1", "request_name": "freespin_buy", "level": "0"},
        {"name": "bonus_2", "request_name": "freespin_buy", "level": "1"},
    ]

    routes = [
        {
            "semantic": "BUY_BONUS",
            "control": "buy-bonus-1",
            "wire_markers": ["command=spin"],
            "status": "NETWORK_INFERRED",
            "interface_role": "network_action",
        },
        {
            "semantic": "BUY_BONUS",
            "control": "buy-bonus-2",
            "wire_markers": ["command=spin"],
            "status": "NETWORK_INFERRED",
            "interface_role": "network_action",
        },
    ]
    _seed_api_v2_buy_feature_routes(routes, evidence)
    assert routes[0]["wire_markers"] == [
        "command=spin",
        "purchased_feature=freespin_buy",
        "purchased_feature_level=0",
    ]
    assert routes[1]["wire_markers"] == [
        "command=spin",
        "purchased_feature=freespin_buy",
        "purchased_feature_level=1",
    ]



def test_api_v2_init_feature_options_seed_all_purchase_levels():
    evidence = EvidenceBundle(
        http=[
            HttpExchange(
                evidence_id="init",
                method="POST",
                url="https://demo.bgaming-network.com/api/Foo/1/session",
                request_body={"command": "init", "extra_data": {"round_series_id": 1}},
                response_status=200,
                response_body={
                    "options": {
                        "feature_options": {
                            "feature_multipliers": {
                                "base_bet": 10,
                                "bonus_buy": {"0": 750, "1": 2000},
                                "bonus_chance": 20,
                            },
                            "disabled_features": [],
                        }
                    }
                },
            )
        ]
    )

    rows = _api_v2_declared_feature_rows(evidence)
    assert rows == [
        {
            "name": "bonus_buy",
            "request_name": "bonus_buy",
            "level": "0",
            "multiplier": 75.0,
        },
        {
            "name": "bonus_buy",
            "request_name": "bonus_buy",
            "level": "1",
            "multiplier": 200.0,
        },
        {
            "name": "bonus_chance",
            "request_name": "bonus_chance",
            "level": "",
            "multiplier": 2.0,
        },
    ]

    routes = []
    _seed_api_v2_buy_feature_routes(routes, evidence)

    assert len(routes) == 3
    assert all(route["static_api_v2"] is True for route in routes)
    assert routes[0]["wire_markers"] == [
        "command=spin",
        "purchased_feature=bonus_buy",
        "purchased_feature_level=0",
    ]
    assert routes[2]["wire_markers"] == [
        "command=spin",
        "purchased_feature=bonus_chance",
    ]
