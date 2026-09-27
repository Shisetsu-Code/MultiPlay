import json

from multiplay.action_graph import build_action_graph, render_action_graph


def test_action_graph_traces_button_to_observed_spin(tmp_path):
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
                            "text": '{"ok":true}',
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
                                'const ui={c:"Button",p:{name:"spin-button",'
                                'onClick:"game.spinClick"}};'
                                'class Game{spinClick(){this.spin()}'
                                'spin(){this.requestCommand("spin")}'
                                'requestCommand(name){return fetch("/api",{method:"POST",'
                                'body:JSON.stringify({command:name})})}}'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "spin.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path)
    route = next(item for item in graph["routes"] if item["semantic"] == "SPIN")

    assert route["control"] == "spin-button"
    assert route["status"] == "NETWORK_OBSERVED"
    assert route["chain"][:2] == ["spinClick", "spin"]
    assert "command=spin" in route["wire_markers"]
    assert route["replay_action_id"]

    detail = render_action_graph(graph, route_id=route["route_id"])
    assert "spin-button" in detail
    assert "command=spin" in detail


def test_action_graph_keeps_popup_opener_separate_from_purchase(tmp_path):
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
                                'const a={c:"Button",p:{name:"buy-bonus-button",'
                                'onClick:"game.openBuyPopup"}};'
                                'const b={c:"Button",p:{name:"buy-confirm",'
                                'onClick:"game.buyBonus"}};'
                                'class Game{openBuyPopup(){this.showModal("buy")}'
                                'buyBonus(){this.api.play({req:{bet:40,'
                                'purchased_feature:"buy_bonus"}})}}'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "buy.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path, include_all=True)
    opener = next(item for item in graph["routes"] if item["control"] == "buy-bonus-button")
    confirm = next(item for item in graph["routes"] if item["control"] == "buy-confirm")

    assert opener["status"] != "NETWORK_OBSERVED"
    assert confirm["status"] == "NETWORK_OBSERVED"
    assert "purchased_feature=buy_bonus" in confirm["wire_markers"]
