import json

import pytest

from multiplay.providers.bgaming.api_v2 import extract_api_v2_templates
from multiplay.providers.bgaming.direct_port import (
    BGamingDemoDirectSession,
    _api_v2_purchase_retry_payloads,
    _marker_map,
    _require_demo_intent,
)


def _write_har(path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://demo.bgaming-network.com/api/Foo/1/session",
                        "headers": [],
                        "postData": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "command": "spin",
                                    "options": {"bet": 100},
                                    "extra_data": {"round_series_id": 1},
                                }
                            ),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "options": {"available_bets": [100]},
                                    "flow": {"available_actions": ["spin"]},
                                }
                            ),
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://demo.bgaming-network.com/app.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/javascript",
                            "text": (
                                'const ui={c:"Button",p:{name:"spin-button",'
                                'onClick:"game.spinClick"}};'
                                'class Game{spinClick(){this.spin()}'
                                'spin(){this.requestCommand("spin")}}'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path.write_text(json.dumps(har), encoding="utf-8")


def test_direct_session_classifies_api_v2_without_opening_network(tmp_path):
    path = tmp_path / "game.har"
    _write_har(path)
    session = BGamingDemoDirectSession(
        har_path=path,
        url="https://demo.bgaming-network.com/play/Foo/FUN",
    )
    assert session.family == "api-v2"
    assert any(
        "command=spin" in action.wire_markers
        for action in session.actions()
    )


def test_marker_map():
    assert _marker_map(("command=spin", "purchased_feature=buy_bonus")) == {
        "command": "spin",
        "purchased_feature": "buy_bonus",
    }


def test_direct_port_rejects_non_demo_direct_url():
    with pytest.raises(ValueError, match="demo/FUN"):
        _require_demo_intent("https://example.bgaming-network.com/play/Foo/REAL")



def test_direct_session_maps_executable_spin_route(tmp_path):
    path = tmp_path / "game.har"
    _write_har(path)
    session = BGamingDemoDirectSession(
        har_path=path,
        url="https://demo.bgaming-network.com/play/Foo/FUN",
    )
    route = next(item for item in session.routes() if item["semantic"] == "SPIN")
    assert route["replay_action_id"]
    assert route["executable"] is False
    assert "not executable in this session" in route["execution_reason"]



def test_inferred_api_purchase_rejects_ambiguous_features(tmp_path):
    path = tmp_path / "game.har"
    _write_har(path)
    session = BGamingDemoDirectSession(
        har_path=path,
        url="https://demo.bgaming-network.com/play/Foo/FUN",
    )
    with pytest.raises(ValueError, match="exactly one purchased_feature"):
        session.execute_inferred_api_v2_purchase(
            [
                "purchased_feature=freespin_buy",
                "purchased_feature=high_freespin_buy",
            ]
        )



def test_inferred_api_purchase_keeps_observed_spin_command(tmp_path):
    path = tmp_path / "game.har"
    _write_har(path)
    session = BGamingDemoDirectSession(
        har_path=path,
        url="https://demo.bgaming-network.com/play/Foo/FUN",
    )
    session.api_templates = extract_api_v2_templates(session.evidence)
    session.default_bet = 100
    session.endpoint_url = "https://demo.bgaming-network.com/api/Foo/session"
    session.headers = {}

    captured = {}

    class FakeResult:
        status = 200
        text = "{}"

    class FakeHttp:
        def post_json(self, url, payload, **kwargs):
            captured["url"] = url
            captured["payload"] = payload
            return FakeResult()

    session.http = FakeHttp()
    result = session.execute_inferred_api_v2_purchase(
        ["command=play", "purchased_feature=freespin_buy"]
    )

    assert result["success"] is True
    assert captured["payload"]["command"] == "spin"
    assert captured["payload"]["options"]["bet"] == 100
    assert captured["payload"]["options"]["purchased_feature"] == "freespin_buy"



def test_api_v2_purchase_retry_converts_numeric_rows_to_wire_string():
    payload = {
        "command": "spin",
        "options": {
            "bet": 200,
            "rows": 4,
            "purchased_feature": "freespin_buy",
            "purchased_feature_level": "4",
        },
        "extra_data": {"round_series_id": 123},
    }

    retries = _api_v2_purchase_retry_payloads(payload)

    assert len(retries) == 1
    assert retries[0]["options"]["rows"] == "4"
    assert payload["options"]["rows"] == 4
