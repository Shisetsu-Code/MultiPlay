import json

import pytest

from multiplay.providers.bgaming.direct_port import (
    BGamingDemoDirectSession,
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
                }
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
