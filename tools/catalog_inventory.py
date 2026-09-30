from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


LEGACY_CLASSES = {
    "pragmatic": ("PragmaticProvider", "pragmatic"),
    "one_spin4win": ("OneSpin4WinProvider", "one_spin4win"),
    "belatra": ("BelatraProvider", "belatra"),
    "rubyplay": ("RubyPlayProvider", "rubyplay"),
    "redtiger": ("RedTigerProvider", "redtiger"),
}

TARGET_FILES = {
    "bgaming": (
        "https://raw.githubusercontent.com/Shisetsu-Code/Crawler-BGaming/main/targets.txt"
    ),
    "3oaks": (
        "https://raw.githubusercontent.com/Shisetsu-Code/Crawler-3oaks/main/targets.txt"
    ),
}


def _request_text(url: str, timeout: float = 30.0) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/128 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _slug_from_url(url: str) -> str:
    parts = [item for item in urlsplit(url).path.split("/") if item]
    if not parts:
        return ""
    if "games" in parts:
        index = parts.index("games")
        if index + 1 < len(parts):
            return parts[index + 1]
    if "play" in parts:
        index = parts.index("play")
        if index + 1 < len(parts):
            return parts[index + 1]
    return parts[-1]


def _target_inventory(provider: str) -> list[dict[str, Any]]:
    text = _request_text(TARGET_FILES[provider])
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        url = raw.strip()
        if not url or url.startswith("#") or url in seen:
            continue
        seen.add(url)
        slug = _slug_from_url(url)
        browser_url = url
        if provider == "3oaks":
            browser_url = f"https://3oaks.com/games/{slug}"
        rows.append(
            {
                "provider": provider,
                "slug": slug,
                "name": slug.replace("_", " ").replace("-", " ").strip().title(),
                "url": url,
                "browser_url": browser_url,
                "source": "targets.txt",
            }
        )
    return rows


def _legacy_inventory(provider: str, legacy_root: Path) -> list[dict[str, Any]]:
    if str(legacy_root) not in sys.path:
        sys.path.insert(0, str(legacy_root))
    os.environ["TESTER_SPIN_PROVIDER_ONLY"] = provider

    import tester_spin.providers as providers  # type: ignore

    class_name, _key = LEGACY_CLASSES[provider]
    cls = getattr(providers, class_name)
    data_root = Path(os.environ.get("RUNNER_TEMP", ".")) / "tester-spin-catalog"
    adapter = cls(data_root)
    messages: list[str] = []
    games = adapter.crawl_catalog(
        stop_event=threading.Event(),
        progress=lambda message: messages.append(str(message)),
        max_pages=100,
    )

    rows = []
    for game in games:
        rows.append(
            {
                "provider": provider,
                "slug": str(game.slug),
                "name": str(game.name),
                "url": str(game.url),
                "browser_url": str(game.url),
                "symbol": str(game.symbol or ""),
                "thumbnail_url": str(game.thumbnail_url or ""),
                "source": "tester-spin-catalog",
            }
        )
    return rows


def _yggdrasil_inventory() -> list[dict[str, Any]]:
    root = "https://yggdrasilgaming.com/game-provider/yggdrasil-gaming"
    html = _request_text(root)
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for href in hrefs:
        absolute = urljoin(root, href)
        parsed = urlsplit(absolute)
        if (parsed.hostname or "").casefold() != "yggdrasilgaming.com":
            continue
        path = parsed.path.rstrip("/")
        if not path.startswith("/games/"):
            continue
        slug = path.split("/", 2)[-1].strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        rows.append(
            {
                "provider": "yggdrasil",
                "slug": slug,
                "name": slug.replace("-", " ").title(),
                "url": absolute,
                "browser_url": absolute + "#tryit",
                "source": "yggdrasil-provider-page",
            }
        )

    if not rows:
        raise RuntimeError("Yggdrasil catalog produced no /games/ links")
    return rows


def inventory(provider: str, legacy_root: Path | None) -> list[dict[str, Any]]:
    if provider in TARGET_FILES:
        return _target_inventory(provider)
    if provider == "yggdrasil":
        return _yggdrasil_inventory()
    if provider in LEGACY_CLASSES:
        if legacy_root is None:
            raise ValueError("--legacy-root is required for this provider")
        return _legacy_inventory(provider, legacy_root)
    raise ValueError(f"unsupported provider: {provider}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider")
    parser.add_argument("--legacy-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = inventory(args.provider, args.legacy_root)
    rows.sort(key=lambda row: (str(row.get("name") or "").casefold(), str(row["slug"])))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "schema": "multiplay/catalog-inventory/v1",
                "provider": args.provider,
                "count": len(rows),
                "games": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"provider": args.provider, "count": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
