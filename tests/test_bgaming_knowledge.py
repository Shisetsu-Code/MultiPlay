from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

LEDGER = Path("knowledge/providers/bgaming/endpoints.json")


def _walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_persisted_bgaming_ledger_is_sanitized_and_provider_only():
    records = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert records

    for record in records:
        assert record["provider"] == "bgaming"
        endpoint = record["endpoint_template"]
        parsed = urlsplit(endpoint)
        assert not parsed.query
        assert "analytics.google.com" not in endpoint
        assert "doubleclick.net" not in endpoint
        assert "sentry." not in endpoint
        assert "/cdn-cgi/rum" not in endpoint
        assert record["live_state"] == "UNKNOWN"

        for key, value in _walk(record.get("request_format")):
            lowered = key.casefold()
            if any(marker in lowered for marker in ("token", "secret", "password", "csrf")):
                assert value == "<redacted>"


def test_persisted_bgaming_ledger_contains_demonstrated_core_actions():
    records = json.loads(LEDGER.read_text(encoding="utf-8"))
    actions = {record["action"] for record in records}

    assert "spin" in actions
    assert "rpc:play:base" in actions
    assert "rpc:play:variant-buy_bonus" in actions
    assert "switch_variant" in actions
