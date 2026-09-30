from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from multiplay.evidence import HarError, load_har
from multiplay.pipeline import analyze_evidence


def _process_game(browser, provider: str, game: dict[str, Any], root: Path, settle_ms: int):
    slug = str(game.get("slug") or "game")
    target = str(game.get("browser_url") or game.get("url") or "").strip()
    har_path = root / f"{slug}.har"
    started = time.monotonic()
    error = ""

    try:
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=1,
            record_har_path=str(har_path),
            record_har_content="embed",
            record_har_mode="full",
        )
        page = context.new_page()

        def route_handler(route):
            kind = route.request.resource_type
            if kind in {"image", "media", "font"}:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_handler)
        page.goto(target, wait_until="domcontentloaded", timeout=25_000)
        page.wait_for_timeout(max(500, int(settle_ms)))
        context.close()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        try:
            context.close()
        except Exception:  # noqa: BLE001
            pass

    if not har_path.is_file():
        return {
            **game,
            "status": "UNAVAILABLE",
            "recognized": False,
            "confidence": 0.0,
            "protocol_families": [],
            "blockers": [],
            "error": error or "HAR was not produced",
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
        }

    try:
        evidence = load_har(har_path)
        result = analyze_evidence(evidence, provider=provider)
        payload = result.to_dict()
        decision = payload.get("provider_decision") or {}
        row = {
            **game,
            "status": str(payload.get("status") or "PARTIAL_REQUIRES_REVIEW"),
            "recognized": bool(decision.get("recognized")),
            "confidence": float(decision.get("confidence") or 0.0),
            "protocol_families": [
                str(item.get("family") or "")
                for item in payload.get("contracts") or []
                if item.get("family")
            ],
            "blockers": list(payload.get("provider_blockers") or []),
            "reasons": list(payload.get("reasons") or []),
            "http_count": len(evidence.http),
            "websocket_count": len(evidence.websocket),
            "error": error,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
        }
        return row
    except (HarError, json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
        return {
            **game,
            "status": "UNAVAILABLE",
            "recognized": False,
            "confidence": 0.0,
            "protocol_families": [],
            "blockers": [],
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--settle-ms", type=int, default=1800)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    all_games = list(catalog.get("games") or [])
    games = [
        game
        for index, game in enumerate(all_games)
        if index % args.shard_count == args.shard_index
    ]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install MultiPlay with browser extra") from exc

    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=f"multiplay-{args.provider}-") as temp:
        root = Path(temp)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-background-networking",
                    "--disable-component-update",
                ],
            )
            for game in games:
                row = _process_game(
                    browser,
                    args.provider,
                    game,
                    root,
                    args.settle_ms,
                )
                rows.append(row)
                print(
                    json.dumps(
                        {
                            "provider": args.provider,
                            "slug": row.get("slug"),
                            "status": row.get("status"),
                            "recognized": row.get("recognized"),
                            "http": row.get("http_count", 0),
                            "ws": row.get("websocket_count", 0),
                            "error": row.get("error") or "",
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            browser.close()

    counts = Counter(str(row.get("status") or "UNKNOWN") for row in rows)
    recognized = sum(1 for row in rows if row.get("recognized"))
    document = {
        "schema": "multiplay/passive-provider-sweep/v1",
        "provider": args.provider,
        "catalog_count": len(all_games),
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "processed": len(rows),
        "recognized": recognized,
        "status_counts": dict(sorted(counts.items())),
        "games": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "provider": args.provider,
                "processed": len(rows),
                "recognized": recognized,
                "status_counts": dict(sorted(counts.items())),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
