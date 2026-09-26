import json

from multiplay.har_map import build_har_map, render_har_map


def test_har_map_links_js_control_to_observed_endpoint(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://game.example/api",
                        "headers": [],
                        "postData": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "jsonrpc": "2.0",
                                    "method": "play",
                                    "params": {
                                        "token": "secret",
                                        "req": {
                                            "bet": 40,
                                            "purchased_feature": "buy_bonus",
                                        },
                                    },
                                }
                            ),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/json",
                            "text": '{"result":{"final":true}}',
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://game.example/app.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/javascript",
                            "text": (
                                'const label="BUY BONUS";'
                                'buyButton.on("pointerup",()=>send({'
                                'method:"play",params:{req:{'
                                'purchased_feature:"buy_bonus"}}}));'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "sample.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    report = build_har_map(path)

    endpoint = next(item for item in report["endpoints"] if item["method"] == "POST")
    control = next(
        item
        for item in report["actions"]
        if item["kind"] == "js_control"
        and "purchased_feature=buy_bonus" in item["wire_markers"]
    )

    assert endpoint["endpoint_template"] == "https://game.example/api"
    assert endpoint["endpoint_id"] in control["endpoint_ids"]
    assert control["event"] == "pointerup"
    assert "secret" not in repr(report)

    detail = render_har_map(report, action_id=control["action_id"])
    assert "buy_bonus" in detail
    assert "https://game.example/api" in detail


def test_har_map_extracts_html_button(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://example.test/",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "text/html",
                            "text": '<button aria-label="BUY FREE SPINS" onclick="openBonus()">X</button>',
                        },
                    },
                }
            ]
        }
    }
    path = tmp_path / "button.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    report = build_har_map(path)
    button = next(item for item in report["actions"] if item["kind"] == "html_control")
    assert button["label"] == "BUY FREE SPINS"
    assert button["event"] == "click"
