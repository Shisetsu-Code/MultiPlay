from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HTTP_FIXTURES = {
    "pragmatic": [
        (
            "https://demogamesfree.pragmaticplay.net/gs2c/v4/gameService",
            {"action": "doSpin", "symbol": "vsTest", "index": "2", "counter": "2"},
            {"na": "c", "win": "1"},
        ),
        (
            "https://demogamesfree.pragmaticplay.net/gs2c/v4/gameService",
            {"action": "doCollect", "symbol": "vsTest", "index": "3", "counter": "3"},
            {"na": "s", "fs": "0"},
        ),
    ],
    "belatra": [
        (
            "https://demo.bltr-static.com/game",
            {"action": "enter", "sid": "secret"},
            {"phaseCur": "idle", "phaseNext": "toStart"},
        ),
        (
            "https://demo.bltr-static.com/game",
            {"action": "start", "sid": "secret"},
            {"phaseCur": "started", "phaseNext": "toPaid"},
        ),
        (
            "https://demo.bltr-static.com/game",
            {"action": "finish", "sid": "secret"},
            {"phaseCur": "finished", "phaseNext": "toIdle"},
        ),
    ],
    "rubyplay": [
        (
            "https://runtime.example/gameserver/demo",
            {"v_protocol": 1, "v_math": 2, "key": "secret", "action": "init"},
            {
                "status": "ok",
                "topic": "gameserver/init",
                "data": {"an": 1, "next_action": "spin"},
            },
        ),
        (
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
    ],
    "redtiger": [
        (
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
        (
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
    ],
    "3oaks": [
        (
            "https://demo.3oaks.com/api/v1/games/example/play?lang=en",
            {"command": "spin", "options": {"bet": "10"}},
            {"status": "ok", "result": {"win": 0}},
        ),
    ],
}


def http_har(rows):
    entries = []
    for url, request_body, response_body in rows:
        entries.append(
            {
                "request": {
                    "method": "POST",
                    "url": url,
                    "headers": [],
                    "postData": {
                        "mimeType": "application/json",
                        "text": json.dumps(request_body, separators=(",", ":")),
                    },
                },
                "response": {
                    "status": 200,
                    "headers": [],
                    "content": {
                        "mimeType": "application/json",
                        "text": json.dumps(response_body, separators=(",", ":")),
                    },
                },
            }
        )
    return {"log": {"version": "1.2", "entries": entries}}


def d1_har():
    url = "wss://gs.1spin4win.com:443/games"
    return {
        "log": {
            "version": "1.2",
            "entries": [
                {
                    "request": {"method": "GET", "url": url, "headers": []},
                    "response": {
                        "status": 101,
                        "headers": [],
                        "content": {"mimeType": "", "text": ""},
                    },
                    "_webSocketMessages": [
                        {
                            "type": "send",
                            "data": 'A/u2{"type":"0","data":",,freeplay,Game,1,config,EUR,test"}',
                        },
                        {
                            "type": "receive",
                            "data": 'A/u2{"type":"1","l":20,"b3":0}',
                        },
                        {
                            "type": "send",
                            "data": 'A/u2{"type":"1","data":"20,0,0"}',
                        },
                        {
                            "type": "receive",
                            "data": 'A/u2{"type":"3","st":0,"win":0}',
                        },
                    ],
                }
            ],
        }
    }


def run(provider: str) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"multiplay-{provider}-") as raw:
        root = Path(raw)
        har_path = root / "fixture.har"
        output_path = root / "analysis.json"
        knowledge_root = root / "knowledge"

        fixture = d1_har() if provider == "one_spin4win" else http_har(HTTP_FIXTURES[provider])
        har_path.write_text(json.dumps(fixture), encoding="utf-8")

        command = [
            "multiplay",
            "analyze-har",
            str(har_path),
            "--provider",
            provider,
            "--source-ref",
            f"github-actions:{provider}",
            "--knowledge-root",
            str(knowledge_root),
            "--output",
            str(output_path),
        ]
        completed = subprocess.run(command, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(
                f"{provider}: CLI failed with {completed.returncode}\n"
                f"stdout={completed.stdout}\nstderr={completed.stderr}"
            )

        result = json.loads(output_path.read_text(encoding="utf-8"))
        decision = result.get("provider_decision") or {}
        blockers = result.get("provider_blockers") or []
        if decision.get("recognized") is not True:
            raise AssertionError(f"{provider}: provider was not recognized: {decision!r}")
        if blockers:
            raise AssertionError(f"{provider}: unexpected blockers: {blockers!r}")
        if result.get("status") != "WIRE_COMPLETE":
            raise AssertionError(f"{provider}: status={result.get('status')!r}")

        endpoint_path = knowledge_root / provider / "endpoints.json"
        if not endpoint_path.is_file():
            raise AssertionError(f"{provider}: endpoint ledger was not written")
        endpoints = json.loads(endpoint_path.read_text(encoding="utf-8"))
        if not endpoints:
            raise AssertionError(f"{provider}: endpoint ledger is empty")

        return {
            "provider": provider,
            "status": result["status"],
            "confidence": decision.get("confidence"),
            "endpoint_count": len(endpoints),
            "actions": sorted({str(item.get("action") or "") for item in endpoints}),
        }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: provider_smoke.py <provider>", file=sys.stderr)
        return 2
    provider = sys.argv[1]
    allowed = {*HTTP_FIXTURES, "one_spin4win"}
    if provider not in allowed:
        print(f"unknown provider: {provider}", file=sys.stderr)
        return 2

    summary = run(provider)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
