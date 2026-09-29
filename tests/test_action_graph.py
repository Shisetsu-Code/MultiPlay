import json

from multiplay.action_graph import (
    _feature_markers_from_body,
    _handler_wire_markers,
    build_action_graph,
    render_action_graph,
)


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



def test_action_graph_links_legacy_spin_desktop(tmp_path):
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
                                    "options": {"bets": {"0": 1}},
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
    path = tmp_path / "legacy-spin.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path)
    route = next(item for item in graph["routes"] if item["semantic"] == "SPIN")
    assert route["control"] == "spinDesktop"
    assert route["status"] == "NETWORK_OBSERVED"
    assert route["wire_markers"] == ["command=spin"]



def test_action_graph_does_not_promote_legacy_freespin_from_base_spin(tmp_path):
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
                                    "options": {"bets": {"0": 1}},
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
                                'u.a.addListener(r.createButton("freespinDesktop",'
                                'i.DESKTOP_CENTER_ALT),this.spin);'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "legacy-freespin.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path, include_all=True)
    route = next(item for item in graph["routes"] if item["control"] == "freespinDesktop")
    assert route["semantic"] == "FREESPIN"
    assert route["status"] != "NETWORK_OBSERVED"
    assert route["replay_action_id"] == ""


def test_action_graph_keeps_chance_separate_from_bonus_purchase(tmp_path):
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
                                    "options": {
                                        "bet": 20,
                                        "purchased_feature": "freespin_buy",
                                    },
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
                                'const ui={c:"Button",p:{name:"double-chance-btn",'
                                'onClick:"all.buy-features.switchChance'
                                '`freespin_chance"}};'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "chance.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path, include_all=True)
    route = next(item for item in graph["routes"] if item["control"] == "double-chance-btn")
    assert route["semantic"] == "CHANCE"
    assert route["status"] != "NETWORK_OBSERVED"
    assert route["replay_action_id"] == ""



def test_action_graph_keeps_purchase_variants_separate(tmp_path):
    def exchange(feature):
        return {
            "request": {
                "method": "POST",
                "url": "https://game.example/api",
                "headers": [],
                "postData": {
                    "mimeType": "application/json",
                    "text": json.dumps(
                        {
                            "command": "spin",
                            "options": {
                                "bet": 20,
                                "purchased_feature": feature,
                            },
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
        }

    tick = chr(96)
    har = {
        "log": {
            "entries": [
                exchange("freespin_buy"),
                exchange("high_freespin_buy"),
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
                                'const a={c:"Button",p:{name:"buy-confirm",'
                                'onClick:"all.buy-features.buyBonusClick'
                                + tick
                                + 'freespin_buy"}};'
                                'const b={c:"Button",p:{name:"buy-confirm",'
                                'onClick:"all.buy-features.buyBonusClick'
                                + tick
                                + 'high_freespin_buy"}};'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "variants.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path)
    routes = [
        item
        for item in graph["routes"]
        if item["semantic"] == "BUY_BONUS"
        and item["control"] == "buy-confirm"
    ]

    assert len(routes) == 2
    handlers = {item["handler"] for item in routes}
    assert handlers == {
        "all.buy-features.buyBonusClick" + tick + "freespin_buy",
        "all.buy-features.buyBonusClick" + tick + "high_freespin_buy",
    }
    features = {
        next(
            marker
            for marker in item["wire_markers"]
            if marker.startswith("purchased_feature=")
        )
        for item in routes
    }
    assert features == {
        "purchased_feature=freespin_buy",
        "purchased_feature=high_freespin_buy",
    }



def test_action_graph_traces_event_manager_spin_to_hyperhive_play(tmp_path):
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
                                        "req": {"bet": 200},
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
                        "url": "https://game.example/bundle.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/javascript",
                            "text": (
                                'class UI{init(){this.eventManager.addListener('
                                '"start-btn-start",t=>{this.onSpinClick(t)})}'
                                'this.onSpinClick=async(t,e)=>{'
                                'this.network.invoke("play",'
                                '{token:this.network.token,req:{bet:200}}}}'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "event-spin.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path)
    route = next(item for item in graph["routes"] if item["semantic"] == "SPIN")

    assert route["control"] == "start-btn-start"
    assert route["handler"] == "onSpinClick"
    assert route["status"] == "NETWORK_OBSERVED"
    assert route["wire_markers"] == ["method=play"]


def test_action_graph_does_not_promote_event_buy_without_feature(tmp_path):
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
                                        "req": {"bet": 200},
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
                        "url": "https://game.example/bundle.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {
                            "mimeType": "application/javascript",
                            "text": (
                                'class UI{init(){this.eventManager.addListener('
                                '"buy-bonus",t=>{this.onSpinClick(false,t)})}'
                                'this.onSpinClick=async(t,e)=>{'
                                'this.network.invoke("play",'
                                '{token:this.network.token,req:{bet:200}}}}'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "event-buy.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path, include_all=True)
    route = next(item for item in graph["routes"] if item["control"] == "buy-bonus")

    assert route["semantic"] == "BUY_BONUS"
    assert route["status"] != "NETWORK_OBSERVED"
    assert route["replay_action_id"] == ""



def test_action_graph_keeps_protocol_play_without_ui_control(tmp_path):
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
                                    "id": 1,
                                    "jsonrpc": "2.0",
                                    "method": "play",
                                    "params": {
                                        "token": "secret",
                                        "req": {"bet": 100},
                                        "state_lock": "lock",
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
                            "text": '{"result":{"state_lock":"next"}}',
                        },
                    },
                }
            ]
        }
    }
    path = tmp_path / "protocol-only.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path)
    route = next(item for item in graph["routes"] if item["semantic"] == "SPIN")

    assert route["status"] == "NETWORK_OBSERVED"
    assert route["interface_role"] == "protocol_action"
    assert route["control"].startswith("protocol:")
    assert route["replay_action_id"]
    assert "method=play" in route["wire_markers"]



def test_action_graph_resolves_static_buy_freespins_feature(tmp_path):
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
                                    "options": {
                                        "bet": 10,
                                        "purchased_feature": "freespin_buy",
                                    },
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
                                'const F="freespin_buy";'
                                'const ui={c:"Button",p:{name:"buy",'
                                'onClick:"currentScene.buyFreespins"}};'
                                'class Game{buyFreespins(){'
                                'this.setBoughtBonusParameter(F);'
                                'this.isNeedToForceSpin=true}'
                                'setBoughtBonusParameter(t,e=null){'
                                'this.additionalSpinOptions.purchased_feature=t;'
                                'this.additionalSpinOptions.purchased_feature_level=e.toString()'
                                '}}'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "buy-freespins.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path)
    route = next(
        item
        for item in graph["routes"]
        if item["control"] == "buy"
    )

    assert route["semantic"] == "BUY_BONUS"
    assert route["status"] == "NETWORK_OBSERVED"
    assert route["wire_markers"] == [
        "command=spin",
        "purchased_feature=freespin_buy",
    ]



def test_action_graph_links_svelte_spin_to_hyperhive_play(tmp_path):
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
                                        "req": {"bet": 200},
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
                },
            ]
        }
    }
    path = tmp_path / "svelte-hyperhive.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path)
    route = next(
        item
        for item in graph["routes"]
        if item["control"] == "spin-button"
    )

    assert route["semantic"] == "SPIN"
    assert route["status"] == "NETWORK_OBSERVED"
    assert route["interface_role"] == "network_action"
    assert route["handler"] == "v0"
    assert "method=play" in route["wire_markers"]
    assert route["replay_action_id"]



def test_scene_buy_bonus_wrapper_resolves_feature_and_level_separately():
    constants = {"FREESPIN_BUY": {"freespin_buy"}}
    body = "this.buyFeatures.buyBonusClick(this.FREESPIN_BUY,t)"

    assert _feature_markers_from_body(body, constants) == {
        "purchased_feature=freespin_buy"
    }
    assert _handler_wire_markers(
        "BUY_BONUS",
        "currentScene.buyBonusClick\u00602",
    ) == {"purchased_feature_level=2"}
    assert _handler_wire_markers(
        "BUY_BONUS",
        "all.buy-features.buyBonusClick\u0060freespin_buy,4",
    ) == {
        "purchased_feature=freespin_buy",
        "purchased_feature_level=4",
    }



def test_action_graph_does_not_cross_match_purchase_levels(tmp_path):
    tick = chr(96)

    def purchase(level: str) -> dict:
        return {
            "request": {
                "method": "POST",
                "url": "https://game.example/api/Foo/1/session",
                "headers": [],
                "postData": {
                    "mimeType": "application/json",
                    "text": json.dumps(
                        {
                            "command": "spin",
                            "options": {
                                "bet": 2,
                                "purchased_feature": "freespin_buy",
                                "purchased_feature_level": level,
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
                    "text": '{"ok":true}',
                },
            },
        }

    har = {
        "log": {
            "entries": [
                purchase("1"),
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
                                'const a={c:"Button",p:{name:"1",onClick:'
                                '"all.buy-features.buyBonusClick'
                                + tick
                                + 'freespin_buy,1"}};'
                                'const b={c:"Button",p:{name:"2",onClick:'
                                '"all.buy-features.buyBonusClick'
                                + tick
                                + 'freespin_buy,2"}};'
                            ),
                        },
                    },
                },
            ]
        }
    }
    path = tmp_path / "purchase-levels.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    graph = build_action_graph(path, include_all=True)
    level1 = next(
        item
        for item in graph["routes"]
        if item["handler"].endswith("freespin_buy,1")
    )
    level2 = next(
        item
        for item in graph["routes"]
        if item["handler"].endswith("freespin_buy,2")
    )

    assert level1["status"] == "NETWORK_OBSERVED"
    assert "purchased_feature_level=1" in level1["wire_markers"]

    assert level2["status"] != "NETWORK_OBSERVED"
    assert "purchased_feature_level=2" in level2["wire_markers"]
    assert "purchased_feature_level=1" not in level2["wire_markers"]
