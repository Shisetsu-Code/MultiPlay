from __future__ import annotations

import json

import pytest

from multiplay.evidence import load_har
from multiplay.models import EvidenceBundle, HttpExchange, WebSocketFrame
from multiplay.pipeline import analyze_evidence
from multiplay.providers import default_provider_registry


def _http(eid, url, body, response, *, status=200):
    return HttpExchange(
        evidence_id=eid,
        method="POST",
        url=url,
        request_body=body,
        response_status=status,
        response_body=response,
    )


@pytest.mark.parametrize(
    ("provider", "evidence"),
    [
        (
            "pragmatic",
            EvidenceBundle(
                http=[
                    _http(
                        "spin",
                        "https://demogamesfree.pragmaticplay.net/gs2c/v4/gameService",
                        {"action": "doSpin", "symbol": "vsTest", "index": "2", "counter": "2"},
                        {"na": "c", "win": "1"},
                    ),
                    _http(
                        "collect",
                        "https://demogamesfree.pragmaticplay.net/gs2c/v4/gameService",
                        {"action": "doCollect", "symbol": "vsTest", "index": "3", "counter": "3"},
                        {"na": "s", "fs": "0"},
                    ),
                ]
            ),
        ),
        (
            "belatra",
            EvidenceBundle(
                http=[
                    _http(
                        "enter",
                        "https://demo.bltr-static.com/game",
                        {"action": "enter", "sid": "secret"},
                        {"phaseCur": "idle", "phaseNext": "toStart"},
                    ),
                    _http(
                        "start",
                        "https://demo.bltr-static.com/game",
                        {"action": "start", "sid": "secret"},
                        {"phaseCur": "started", "phaseNext": "toPaid"},
                    ),
                    _http(
                        "finish",
                        "https://demo.bltr-static.com/game",
                        {"action": "finish", "sid": "secret"},
                        {"phaseCur": "finished", "phaseNext": "toIdle"},
                    ),
                ]
            ),
        ),
        (
            "rubyplay",
            EvidenceBundle(
                http=[
                    _http(
                        "init",
                        "https://runtime.example/gameserver/demo",
                        {
                            "v_protocol": 1,
                            "v_math": 2,
                            "key": "secret",
                            "action": "init",
                        },
                        {
                            "status": "ok",
                            "topic": "gameserver/init",
                            "data": {"an": 1, "next_action": "spin"},
                        },
                    ),
                    _http(
                        "spin",
                        "https://runtime.example/gameserver/demo",
                        {
                            "v_protocol": 1,
                            "v_math": 2,
                            "key": "secret",
                            "action": "spin",
                            "an": 1,
                            "bet": 10,
                        },
                        {
                            "status": "ok",
                            "topic": "gameserver/spin",
                            "data": {"an": 2, "next_action": "spin"},
                        },
                    ),
                ]
            ),
        ),
        (
            "redtiger",
            EvidenceBundle(
                http=[
                    _http(
                        "settings",
                        "https://runtime.example/platform/game/settings",
                        {"token": "secret", "sessionId": "secret", "gameId": "123"},
                        {
                            "success": True,
                            "result": {
                                "game": {"featureBuy": []},
                                "user": {"stakes": {"types": [10], "defaultIndex": 0}},
                            },
                        },
                    ),
                    _http(
                        "spin",
                        "https://runtime.example/platform/game/spin",
                        {
                            "token": "secret",
                            "sessionId": "secret",
                            "gameId": "123",
                            "stake": 10,
                            "extras": None,
                        },
                        {"success": True, "result": {"game": {"results": []}}},
                    ),
                ]
            ),
        ),
        (
            "3oaks",
            EvidenceBundle(
                http=[
                    _http(
                        "spin",
                        "https://demo.3oaks.com/api/v1/games/example/play?lang=en",
                        {"command": "spin", "options": {"bet": "10"}},
                        {"status": "ok", "result": {"win": 0}},
                    )
                ]
            ),
        ),
    ],
)
def test_migrated_http_provider_reaches_wire_complete(provider, evidence):
    result = analyze_evidence(evidence, provider=provider)

    assert result.provider_decision is not None
    assert result.provider_decision.recognized is True
    assert result.provider_blockers == []
    assert result.analysis.status.value == "WIRE_COMPLETE"


def test_one_spin4win_websocket_contract_reaches_wire_complete():
    url = "wss://gs.1spin4win.com:443/games"
    evidence = EvidenceBundle(
        websocket=[
            WebSocketFrame(
                evidence_id="init-send",
                url=url,
                direction="send",
                payload='A/u2{"type":"0","data":",,freeplay,Game,1,config,EUR,test"}',
                sequence=0,
            ),
            WebSocketFrame(
                evidence_id="init-recv",
                url=url,
                direction="receive",
                payload='A/u2{"type":"1","l":20,"b3":0}',
                sequence=1,
            ),
            WebSocketFrame(
                evidence_id="play-send",
                url=url,
                direction="send",
                payload='A/u2{"type":"1","data":"20,0,0"}',
                sequence=2,
            ),
            WebSocketFrame(
                evidence_id="play-recv",
                url=url,
                direction="receive",
                payload='A/u2{"type":"3","st":0,"win":0}',
                sequence=3,
            ),
        ]
    )

    result = analyze_evidence(evidence, provider="one_spin4win")

    assert result.provider_decision is not None
    assert result.provider_decision.recognized is True
    assert result.provider_blockers == []
    assert result.analysis.status.value == "WIRE_COMPLETE"


def test_one_spin4win_active_feature_without_continuation_stays_partial():
    url = "wss://gs.1spin4win.com:443/games"
    evidence = EvidenceBundle(
        websocket=[
            WebSocketFrame(
                evidence_id="init-send",
                url=url,
                direction="send",
                payload='A/u2{"type":"0","data":",,freeplay,Game,1,config,EUR,test"}',
                sequence=0,
            ),
            WebSocketFrame(
                evidence_id="play-send",
                url=url,
                direction="send",
                payload='A/u2{"type":"1","data":"20,0,0"}',
                sequence=1,
            ),
            WebSocketFrame(
                evidence_id="play-recv",
                url=url,
                direction="receive",
                payload='A/u2{"type":"3","st":5,"win":0}',
                sequence=2,
            ),
        ]
    )

    result = analyze_evidence(evidence, provider="one_spin4win")

    assert result.analysis.status.value == "PARTIAL_REQUIRES_REVIEW"
    assert any("st=5" in reason for reason in result.provider_blockers or [])


def test_har_loader_imports_chromium_websocket_messages(tmp_path):
    url = "wss://gs.1spin4win.com:443/games"
    har = {
        "log": {
            "entries": [
                {
                    "request": {"method": "GET", "url": url, "headers": []},
                    "response": {"status": 101, "headers": [], "content": {"text": ""}},
                    "_webSocketMessages": [
                        {
                            "type": "send",
                            "data": 'A/u2{"type":"0","data":",,freeplay,Game,1,config,EUR,test"}',
                        },
                        {
                            "type": "receive",
                            "data": 'A/u2{"type":"1","l":20,"b3":0}',
                        },
                    ],
                }
            ]
        }
    }
    path = tmp_path / "d1.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    evidence = load_har(path)

    assert len(evidence.websocket) == 2
    assert evidence.websocket[0].direction == "send"
    assert evidence.websocket[1].direction == "receive"


def test_default_registry_contains_all_migrated_providers():
    keys = {adapter.key for adapter in default_provider_registry().all()}

    assert keys == {
        "bgaming",
        "yggdrasil",
        "pragmatic",
        "one_spin4win",
        "belatra",
        "rubyplay",
        "redtiger",
        "3oaks",
    }
