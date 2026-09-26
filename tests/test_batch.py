import json

from multiplay.batch import analyze_har_directory


def _write_har(path, request_body, response_body):
    path.write_text(
        json.dumps(
            {
                "log": {
                    "entries": [
                        {
                            "request": {
                                "method": "POST",
                                "url": (
                                    "https://demo.bgaming-network.com/"
                                    "api/Foo/12345/session"
                                ),
                                "postData": {
                                    "mimeType": "application/json",
                                    "text": json.dumps(request_body),
                                },
                            },
                            "response": {
                                "status": 200,
                                "content": {
                                    "mimeType": "application/json",
                                    "text": json.dumps(response_body),
                                },
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def test_batch_analyzes_multiple_hars_and_builds_provider_knowledge(tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    knowledge = tmp_path / "knowledge"

    for name in ("one.har", "two.har"):
        _write_har(
            captures / name,
            {
                "command": "spin",
                "options": {"bet": 100},
                "extra_data": {"round_series_id": 1},
            },
            {
                "options": {"bets": [100]},
                "flow": {
                    "state": "closed",
                    "available_actions": ["spin"],
                },
                "balance": 900,
            },
        )

    report = analyze_har_directory(
        captures,
        provider="bgaming",
        knowledge_root=knowledge,
    )

    assert report["har_count"] == 2
    assert report["error_counts"] == {}
    assert sum(report["status_counts"].values()) == 2
    assert report["runtime_family_counts"] == {"api-v2": 2}
    assert report["blocker_counts"] == {}
    assert all(item["runtime_families"] == ["api-v2"] for item in report["results"])
    assert (knowledge / "bgaming" / "endpoints.json").is_file()
    assert len(list((knowledge / "bgaming" / "runs").glob("*.json"))) == 2


def test_batch_records_bad_har_without_aborting_other_files(tmp_path):
    captures = tmp_path / "captures"
    captures.mkdir()
    (captures / "bad.har").write_text("not-json", encoding="utf-8")
    _write_har(
        captures / "good.har",
        {
            "command": "spin",
            "options": {"bet": 100},
            "extra_data": {"round_series_id": 1},
        },
        {
            "options": {"bets": [100]},
            "flow": {"state": "closed", "available_actions": ["spin"]},
        },
    )

    report = analyze_har_directory(
        captures,
        provider="bgaming",
        knowledge_root=tmp_path / "knowledge",
    )

    assert report["har_count"] == 2
    assert report["error_counts"]["JSONDecodeError"] == 1
    assert any(item["status"] != "ERROR" for item in report["results"])
