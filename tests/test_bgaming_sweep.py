from __future__ import annotations

from multiplay.models import EvidenceBundle, HttpExchange
from multiplay.providers.bgaming.probe import ProbeMetadata, ProbeResult
from multiplay.providers.bgaming.sweep import sweep_catalog_payload


def _probe(_url, *, timeout_s):
    del timeout_s
    return ProbeResult(
        evidence=EvidenceBundle(
            http=[
                HttpExchange(
                    evidence_id="probe:init",
                    method="POST",
                    url="https://demo.bgaming-network.com/api/Foo/12345/session",
                    request_body={
                        "command": "init",
                        "extra_data": {"round_series_id": 1},
                    },
                    response_status=200,
                    response_body={
                        "options": {"bets": [100]},
                        "flow": {"state": "closed", "available_actions": ["spin"]},
                    },
                )
            ]
        ),
        metadata=ProbeMetadata(
            requested_url="https://bgaming.com/games/foo/",
            launch_url="https://demo.bgaming-network.com/play/Foo/x/y",
            identifier="Foo",
            bootstrap_available=True,
            init_executed=True,
        ),
    )


def test_sweep_classifies_runtime_and_records_status(tmp_path):
    payload = {
        "authoritative": True,
        "records": [
            {
                "slug": "foo",
                "name": "Foo",
                "public_url": "https://bgaming.com/games/foo/",
                "execution_url": "https://bgaming.com/games/foo/",
                "demo_url": "",
                "availability": "EPHEMERAL_DEMO",
            }
        ],
    }

    report = sweep_catalog_payload(
        payload,
        delay_s=0,
        knowledge_root=tmp_path,
        probe_fn=_probe,
    )

    assert report["attempted"] == 1
    assert report["runtime_family_counts"] == {"api-v2": 1}
    assert report["failure_counts"] == {}
    assert report["results"][0]["target_kind"] == "PUBLIC_RESOLVE"
    assert (tmp_path / "bgaming" / "endpoints.json").exists()


def test_sweep_keeps_probe_failures_in_report(tmp_path):
    def fail(_url, *, timeout_s):
        del timeout_s
        raise RuntimeError("blocked")

    payload = {
        "authoritative": True,
        "records": [
            {
                "slug": "foo",
                "name": "Foo",
                "public_url": "https://bgaming.com/games/foo/",
                "execution_url": "https://bgaming.com/games/foo/",
                "availability": "NO_DEMO",
            }
        ],
    }

    report = sweep_catalog_payload(
        payload,
        delay_s=0,
        knowledge_root=tmp_path,
        probe_fn=fail,
    )

    assert report["attempted"] == 1
    assert report["failure_counts"] == {"RuntimeError": 1}
    assert report["results"][0]["status"] == "ERROR"
