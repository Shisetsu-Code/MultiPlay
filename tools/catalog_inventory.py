from __future__ import annotations

import argparse
import html
import json
import re
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


TARGET_FILES = {
    "bgaming": "https://raw.githubusercontent.com/Shisetsu-Code/Crawler-BGaming/main/targets.txt",
    "3oaks": "https://raw.githubusercontent.com/Shisetsu-Code/Crawler-3oaks/main/targets.txt",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
)


def _request(url: str, timeout: float = 30.0):
    request = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
        },
    )
    context = ssl.create_default_context()
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    return urlopen(request, timeout=timeout, context=context)


def _request_text(url: str, timeout: float = 30.0) -> str:
    with _request(url, timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _request_json(url: str, timeout: float = 30.0) -> tuple[Any, dict[str, str]]:
    with _request(url, timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        headers = {str(k): str(v) for k, v in response.headers.items()}
    return json.loads(body), headers


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value or ""))).strip()


def _slug_title(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


def _hrefs(text: str, base_url: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r'href\s*=\s*["\']([^"\']+)["\']', text or "", re.I):
        url = urljoin(base_url, html.unescape(raw.strip()))
        if url not in seen:
            seen.add(url)
            values.append(url)
    return values


def _browser_hrefs(
    url: str,
    *,
    load_more: bool = False,
    timeout_ms: int = 60_000,
) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
        )
        page = context.new_page()

        def route_handler(route):
            if route.request.resource_type in {"image", "media", "font"}:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_handler)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1800)

        if load_more:
            previous = -1
            stagnant = 0
            for _ in range(40):
                href_count = page.locator("a[href]").count()
                if href_count == previous:
                    stagnant += 1
                else:
                    stagnant = 0
                previous = href_count
                if stagnant >= 3:
                    break

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(350)
                clicked = False
                for pattern in (
                    r"load more",
                    r"show more",
                    r"more games",
                    r"view more",
                ):
                    try:
                        locator = page.get_by_text(re.compile(pattern, re.I)).first
                        if locator.count() and locator.is_visible():
                            locator.click(timeout=1500)
                            clicked = True
                            page.wait_for_timeout(700)
                            break
                    except Exception:
                        continue
                if not clicked:
                    page.wait_for_timeout(250)

        values = page.locator("a[href]").evaluate_all(
            "(nodes) => nodes.map(n => n.href).filter(Boolean)"
        )
        context.close()
        browser.close()

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        href = str(value or "").strip()
        if href and href not in seen:
            seen.add(href)
            out.append(href)
    return out


def _slug_from_url(url: str) -> str:
    parts = [item for item in urlsplit(url).path.split("/") if item]
    if not parts:
        return ""
    for marker in ("games", "play"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return parts[index + 1]
    return parts[-1]


def _row(provider: str, slug: str, url: str, *, name: str = "", symbol: str = ""):
    return {
        "provider": provider,
        "slug": slug,
        "name": name or _slug_title(slug),
        "url": url,
        "browser_url": url,
        "symbol": symbol,
        "source": "live-catalog",
    }


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
        item = _row(provider, slug, url)
        item["source"] = "targets.txt"
        if provider == "3oaks":
            item["browser_url"] = f"https://3oaks.com/games/{slug}"
        rows.append(item)
    return rows


def _pragmatic_inventory() -> list[dict[str, Any]]:
    root = "https://www.pragmaticplay.com/en/games/"
    found: dict[str, dict[str, Any]] = {}
    empty = 0
    for page in range(1, 101):
        url = root if page == 1 else urljoin(root, f"page/{page}/")
        try:
            text = _request_text(url)
        except HTTPError as exc:
            if exc.code == 404:
                break
            raise
        candidates = _hrefs(text, url)
        if not any("/games/game/" in urlsplit(item).path for item in candidates):
            candidates = _browser_hrefs(url)

        new_count = 0
        for href in candidates:
            parsed = urlsplit(href)
            match = re.fullmatch(r"/en/games/([^/?#]+)/?", parsed.path, re.I)
            if not match:
                continue
            slug = match.group(1).casefold()
            if slug in found:
                continue
            found[slug] = _row(
                "pragmatic",
                slug,
                f"https://www.pragmaticplay.com/en/games/{slug}/",
            )
            new_count += 1
        empty = empty + 1 if new_count == 0 else 0
        if empty >= 2:
            break
    if not found:
        raise RuntimeError("Pragmatic catalog produced no game links")
    return list(found.values())


def _one_spin_inventory() -> list[dict[str, Any]]:
    root = "https://www.1spin4win.com/games"
    found: dict[str, dict[str, Any]] = {}
    visited: set[str] = set()
    url = root

    for _page in range(100):
        if not url or url in visited:
            break
        visited.add(url)
        text = _request_text(url)
        hrefs = _hrefs(text, url)

        for href in hrefs:
            parsed = urlsplit(href)
            host = (parsed.hostname or "").casefold()
            if host != "gs.1spin4win.com":
                continue
            query = parse_qs(parsed.query)
            slug = str((query.get("game") or [""])[0]).strip()
            if not slug:
                slug = Path(parsed.path).stem
            slug = slug.strip().casefold()
            if slug and slug not in found:
                found[slug] = _row("one_spin4win", slug, href)

        next_candidates: list[tuple[int, str]] = []
        for href in hrefs:
            parsed = urlsplit(href)
            query = parse_qs(parsed.query)
            for key, values in query.items():
                if not key.endswith("_page"):
                    continue
                try:
                    page_number = int((values or ["0"])[0])
                except ValueError:
                    continue
                if href not in visited:
                    next_candidates.append((page_number, href))
        url = min(next_candidates, default=(0, ""))[1]

    if not found:
        raise RuntimeError("1Spin4Win catalog produced no gs.1spin4win.com demos")
    return list(found.values())


def _belatra_next_stream(payload: str) -> str:
    text = payload or ""
    marker = 'self.__next_f.push([1,"'
    if marker not in text:
        return text

    chunks: list[str] = []
    for script in re.findall(r"<script[^>]*>(.*?)</script>", text, re.I | re.S):
        if marker not in script:
            continue
        begin = script.find(marker)
        if begin < 0:
            continue
        begin += len(marker)
        finish = script.rfind('"])')
        if finish <= begin:
            continue
        raw = script[begin:finish]
        try:
            chunks.append(json.loads('"' + raw + '"'))
        except json.JSONDecodeError:
            continue
    return "".join(chunks) if chunks else text


def _belatra_game_objects(stream: str) -> list[dict[str, Any]]:
    needle = '"games":'
    offset = 0
    decoder = json.JSONDecoder()
    best: list[dict[str, Any]] = []
    while True:
        index = stream.find(needle, offset)
        if index < 0:
            return best
        try:
            value, _end = decoder.raw_decode(stream[index + len(needle) :])
        except json.JSONDecodeError:
            offset = index + len(needle)
            continue
        if isinstance(value, list):
            candidates = [
                item
                for item in value
                if isinstance(item, dict)
                and str(item.get("slug") or "").strip()
                and str(item.get("title") or "").strip()
            ]
            if len(candidates) > len(best):
                best = candidates
        offset = index + len(needle)


def _belatra_pagination_meta(stream: str) -> dict[str, Any]:
    needle = '"meta":'
    offset = 0
    decoder = json.JSONDecoder()
    while True:
        index = stream.find(needle, offset)
        if index < 0:
            return {}
        try:
            value, _end = decoder.raw_decode(stream[index + len(needle) :])
        except json.JSONDecodeError:
            offset = index + len(needle)
            continue
        if (
            isinstance(value, dict)
            and "current_page" in value
            and "last_page" in value
            and "per_page" in value
        ):
            return value
        offset = index + len(needle)


def _belatra_inventory() -> list[dict[str, Any]]:
    root = "https://belatragames.com/es/games/category/2"
    found: dict[str, dict[str, Any]] = {}
    expected_last_page: int | None = None

    for page in range(1, 101):
        url = root if page == 1 else f"{root}/{page}"
        try:
            text = _request_text(url)
        except HTTPError as exc:
            if exc.code == 404:
                break
            raise

        stream = _belatra_next_stream(text)
        games = _belatra_game_objects(stream)
        meta = _belatra_pagination_meta(stream)

        if games:
            parsed = urlsplit(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            language_parts = [part for part in parsed.path.split("/") if part]
            language = (
                language_parts[0].casefold()
                if language_parts
                and re.fullmatch(r"[a-z]{2}", language_parts[0], re.I)
                else "en"
            )
            for item in games:
                slug = str(item.get("slug") or "").strip().casefold()
                if not slug:
                    continue
                name = str(item.get("title") or "").strip() or _slug_title(slug)
                provider_id = str(item.get("id") or "").strip()
                found[slug] = _row(
                    "belatra",
                    slug,
                    f"{origin}/{language}/games/game/{slug}",
                    name=name,
                    symbol=provider_id or slug,
                )
        else:
            candidates = _browser_hrefs(url)
            for href in candidates:
                parsed = urlsplit(href)
                match = re.fullmatch(
                    r"/(?:[a-z]{2}/)?games/game/([^/?#]+)/?",
                    parsed.path,
                    re.I,
                )
                if not match:
                    continue
                slug = match.group(1).casefold()
                found.setdefault(slug, _row("belatra", slug, href))

        try:
            last_page = int(meta.get("last_page") or 0)
        except (TypeError, ValueError):
            last_page = 0
        if last_page > 0:
            expected_last_page = last_page

        if expected_last_page is not None and page >= expected_last_page:
            break
        if not games and not meta and page >= 2:
            break

    if not found:
        raise RuntimeError("Belatra catalog produced no games from Next.js RSC data")
    return list(found.values())


def _rubyplay_wp_inventory() -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for page in range(1, 101):
        query = urlencode({"per_page": 100, "page": page})
        url = f"https://rubyplay.com/wp-json/wp/v2/games?{query}"
        try:
            payload, headers = _request_json(url)
        except HTTPError as exc:
            if exc.code in {400, 404} and page > 1:
                break
            raise
        if not isinstance(payload, list):
            raise RuntimeError("RubyPlay wp-json games response is not a list")
        for item in payload:
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or "").strip().casefold()
            link = str(item.get("link") or "").strip()
            title = item.get("title")
            rendered = title.get("rendered") if isinstance(title, dict) else ""
            if slug and link:
                found[slug] = _row(
                    "rubyplay",
                    slug,
                    link,
                    name=_strip_tags(str(rendered or "")),
                    symbol=str(item.get("id") or ""),
                )
        total_pages = int(headers.get("X-WP-TotalPages") or headers.get("x-wp-totalpages") or 0)
        if (total_pages and page >= total_pages) or len(payload) < 100:
            break
    return list(found.values())


def _rubyplay_sitemap_inventory() -> list[dict[str, Any]]:
    roots = [
        "https://rubyplay.com/wp-sitemap-posts-games-1.xml",
        "https://rubyplay.com/game-sitemap.xml",
        "https://rubyplay.com/wp-sitemap.xml",
    ]
    found: dict[str, dict[str, Any]] = {}
    pending = list(roots)
    seen_docs: set[str] = set()

    while pending and len(seen_docs) < 30:
        url = pending.pop(0)
        if url in seen_docs:
            continue
        seen_docs.add(url)
        try:
            text = _request_text(url)
        except Exception:
            continue
        locs = re.findall(r"<loc>\s*([^<]+)\s*</loc>", text, re.I)
        for loc in locs:
            loc = html.unescape(loc.strip())
            parsed = urlsplit(loc)
            match = re.fullmatch(r"/games/([^/]+)/?", parsed.path, re.I)
            if match:
                slug = match.group(1).casefold()
                found[slug] = _row("rubyplay", slug, loc)
            elif "sitemap" in parsed.path.casefold() and "games" in parsed.path.casefold():
                pending.append(loc)

    if not found:
        try:
            text = _request_text("https://rubyplay.com/games/")
            candidates = _hrefs(text, "https://rubyplay.com/games/")
        except Exception:
            candidates = []
        if not candidates:
            candidates = _browser_hrefs(
                "https://rubyplay.com/games/",
                load_more=True,
            )
        for href in candidates:
            match = re.fullmatch(r"/games/([^/]+)/?", urlsplit(href).path, re.I)
            if match:
                slug = match.group(1).casefold()
                found[slug] = _row("rubyplay", slug, href)
    return list(found.values())


def _rubyplay_inventory() -> list[dict[str, Any]]:
    try:
        rows = _rubyplay_wp_inventory()
    except Exception:
        rows = []
    if not rows:
        rows = _rubyplay_sitemap_inventory()
    if not rows:
        raise RuntimeError("RubyPlay catalog produced no game links")
    return rows


def _redtiger_inventory() -> list[dict[str, Any]]:
    endpoint = "https://games.evolution.com/wp-json/wp/v2/pages"
    found: dict[str, dict[str, Any]] = {}
    for page in range(1, 101):
        query = urlencode(
            [
                ("_embed", 1),
                ("acf_format", "standard"),
                ("page", page),
                ("per_page", 100),
                ("game_provider[]", "1185"),
                ("custom_sort", "featured"),
                ("only_games", 1),
            ]
        )
        try:
            payload, headers = _request_json(f"{endpoint}?{query}")
        except HTTPError as exc:
            if exc.code == 400 and page > 1:
                break
            raise
        if not isinstance(payload, list):
            raise RuntimeError("Red Tiger WordPress response is not a list")
        for item in payload:
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or "").strip().casefold()
            link = str(item.get("link") or "").strip()
            title = item.get("title")
            rendered = title.get("rendered") if isinstance(title, dict) else ""
            if slug and link:
                found[slug] = _row(
                    "redtiger",
                    slug,
                    link,
                    name=_strip_tags(str(rendered or "")),
                    symbol=str(item.get("id") or ""),
                )
        total_pages = int(headers.get("X-WP-TotalPages") or headers.get("x-wp-totalpages") or 0)
        if (total_pages and page >= total_pages) or len(payload) < 100:
            break
    if not found:
        raise RuntimeError("Red Tiger catalog produced no provider=1185 games")
    return list(found.values())


def _yggdrasil_inventory() -> list[dict[str, Any]]:
    root = "https://yggdrasilgaming.com/game-provider/yggdrasil-gaming"
    found: dict[str, dict[str, Any]] = {}

    try:
        text = _request_text(root)
        candidates = _hrefs(text, root)
    except Exception:
        candidates = []

    if not any("/games/" in urlsplit(item).path for item in candidates):
        candidates = _browser_hrefs(root, load_more=True)

    for href in candidates:
        parsed = urlsplit(href)
        if (parsed.hostname or "").casefold() != "yggdrasilgaming.com":
            continue
        match = re.fullmatch(r"/games/([^/]+)/?", parsed.path, re.I)
        if not match:
            continue
        slug = match.group(1).casefold()
        item = _row("yggdrasil", slug, href)
        item["browser_url"] = href + "#tryit"
        found[slug] = item
    if not found:
        raise RuntimeError("Yggdrasil catalog produced no /games/ links")
    return list(found.values())


def inventory(provider: str) -> list[dict[str, Any]]:
    if provider in TARGET_FILES:
        return _target_inventory(provider)
    if provider == "pragmatic":
        return _pragmatic_inventory()
    if provider == "one_spin4win":
        return _one_spin_inventory()
    if provider == "belatra":
        return _belatra_inventory()
    if provider == "rubyplay":
        return _rubyplay_inventory()
    if provider == "redtiger":
        return _redtiger_inventory()
    if provider == "yggdrasil":
        return _yggdrasil_inventory()
    raise ValueError(f"unsupported provider: {provider}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider")
    parser.add_argument("--legacy-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = inventory(args.provider)
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
