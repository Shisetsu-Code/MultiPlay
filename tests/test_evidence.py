import json

from multiplay.evidence import load_har


def test_javascript_with_equals_and_ampersands_stays_script_text(tmp_path):
    script = 'const query="a=b&c=d";button={name:"spin-button",onClick:"game.spin"};'
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
                            "text": script,
                        },
                    },
                }
            ]
        }
    }
    path = tmp_path / "script.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    evidence = load_har(path)

    assert evidence.http[0].response_body == script
    assert len(evidence.scripts) == 1
    assert evidence.scripts[0].text == script


def test_urlencoded_payload_still_parses_when_mime_declares_it(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://game.example/api",
                        "headers": [],
                        "postData": {
                            "mimeType": "application/x-www-form-urlencoded",
                            "text": "a=b&c=d",
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
            ]
        }
    }
    path = tmp_path / "form.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    evidence = load_har(path)

    assert evidence.http[0].request_body == {"a": "b", "c": "d"}



def test_urlencoded_yggdrasil_session_fields_are_redacted(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://demo.yggdrasilgaming.com/game.web/service?fn=play",
                        "headers": [],
                        "postData": {
                            "mimeType": "application/x-www-form-urlencoded",
                            "text": (
                                "gameid=10964&gameHistorySessionId=session-secret&"
                                "gameHistoryTicketId=ticket-secret&amount=65&coin=0.1&cmd=BB_2"
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
            ]
        }
    }
    path = tmp_path / "yggdrasil.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    evidence = load_har(path)
    body = evidence.http[0].request_body

    assert body["gameHistorySessionId"] == "<redacted>"
    assert body["gameHistoryTicketId"] == "<redacted>"
    assert body["cmd"] == "BB_2"
    assert body["amount"] == "65"
