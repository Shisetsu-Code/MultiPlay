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



def test_har_map_extracts_legacy_create_button_binding(tmp_path):
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
                                    "command": "spin",
                                    "options": {"bet": 20},
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
                            "text": '{"ok":true}',
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://game.example/casino.min.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/javascript",
                            "text": (
                                'u.a.addListener(r.createButton("spinDesktop",'
                                'i.DESKTOP_CENTER),this.spin);'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "legacy.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    report = build_har_map(path)
    button = next(
        item
        for item in report["actions"]
        if item["kind"] == "declared_button"
        and item["label"] == "spinDesktop"
    )
    assert button["handler"] == "this.spin"
    assert button["event"] == "click"



def test_har_map_extracts_svelte_spin_binding(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://game.example/index.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/javascript",
                            "text": (
                                'function v0(r,t){t.game.onPlaySound("play"),'
                                't.spin.startSpin()}'
                                'function Xb(r,t){var g={};'
                                'g.__pointerdown=[v0,t]}'
                            ),
                        },
                    },
                }
            ]
        }
    }
    path = tmp_path / "svelte-spin.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    report = build_har_map(path)

    control = next(
        item
        for item in report["actions"]
        if item["kind"] == "svelte_control"
    )
    assert control["label"] == "spin-button"
    assert control["handler"] == "v0"
    assert control["event"] == "pointer-down"



def test_har_map_extracts_framework_spin_event(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://game.example/client.min.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/javascript",
                            "text": (
                                'case "GAME_CONTROLS_VL_ON_SPIN_CLICK":'
                                'this.onSpinClicked(),'
                                'this.sharedMainProxy.controlsStateVO.settingsOpened=!1;'
                            ),
                        },
                    },
                }
            ]
        }
    }
    path = tmp_path / "framework-spin.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    report = build_har_map(path)
    control = next(
        item
        for item in report["actions"]
        if item["kind"] == "event_control"
        and item["event"] == "GAME_CONTROLS_VL_ON_SPIN_CLICK"
    )
    assert control["label"] == "spin-button"
    assert control["handler"] == "onSpinClicked"



def test_har_map_resolves_feature_literal_passed_to_spin_handler(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://game.example/bundle.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/javascript",
                            "text": (
                                'this.eventManager.addListener("buy-bonus",()=>{'
                                'this.onSpinClick(!1,"buy_bonus")});'
                            ),
                        },
                    },
                }
            ]
        }
    }
    path = tmp_path / "handler-feature.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    report = build_har_map(path)
    control = next(
        item
        for item in report["actions"]
        if item["kind"] == "event_control"
        and item["label"] == "buy-bonus"
    )
    assert "purchased_feature=buy_bonus" in control["wire_markers"]
