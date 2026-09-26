import hashlib
import json
from pathlib import Path

from multiplay.providers.bgaming.browser_discovery import _prioritize_family_cache


def test_family_cache_prioritizes_only_when_catalog_hash_matches(tmp_path):
    records = [
        {"slug": "a"},
        {"slug": "b"},
        {"slug": "c"},
    ]
    digest = hashlib.sha256(b"a\nb\nc").hexdigest()
    path = Path(tmp_path) / "family-map.json"
    path.write_text(
        json.dumps(
            {
                "schema": "multiplay/bgaming-family-map/v1",
                "catalog_slugs_sha256": digest,
                "entries": {
                    "b": ["hyperhive-jsonrpc"],
                },
            }
        ),
        encoding="utf-8",
    )

    ordered = _prioritize_family_cache(
        records,
        family="hyperhive-jsonrpc",
        family_map_path=path,
    )
    assert [row["slug"] for row in ordered] == ["b", "a", "c"]


def test_family_cache_is_ignored_when_catalog_changes(tmp_path):
    records = [{"slug": "a"}, {"slug": "b"}]
    path = Path(tmp_path) / "family-map.json"
    path.write_text(
        json.dumps(
            {
                "schema": "multiplay/bgaming-family-map/v1",
                "catalog_slugs_sha256": "stale",
                "entries": {"b": ["hyperhive-jsonrpc"]},
            }
        ),
        encoding="utf-8",
    )

    ordered = _prioritize_family_cache(
        records,
        family="hyperhive-jsonrpc",
        family_map_path=path,
    )
    assert ordered == records
