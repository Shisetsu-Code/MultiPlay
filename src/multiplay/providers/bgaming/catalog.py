from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

BGAMING_SLOTS_URL = "https://bgaming.com/game-type/slots"
BGAMING_CATALOG_SEARCH_URL = "https://bgaming.com/wp-json/bg/v1/games/search"
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass(frozen=True, slots=True)
class BGamingCatalogRecord:
    provider: str
    slug: str
    name: str
    public_url: str
    execution_url: str
    demo_url: str
    thumbnail_url: str
    identifier: str
    rtp: float | None
    volatility: str
    game_type: str
    availability: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CatalogCrawlResult:
    records: tuple[BGamingCatalogRecord, ...]
    pages: int
    authoritative: bool
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": "bgaming",
            "record_count": len(self.records),
            "pages": self.pages,
            "authoritative": self.authoritative,
            "diagnostics": list(self.diagnostics),
            "records": [item.to_dict() for item in self.records],
        }


@dataclass(slots=True)
class _Card:
    attrs: dict[str, str] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    name: str = ""
    image_src: str = ""
    all_text: list[str] = field(default_factory=list)
    class_text: dict[str, list[str]] = field(default_factory=dict)


class _CatalogParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.cards: list[_Card] = []
        self._card: _Card | None = None
        self._depth = 0
        self._class_stack: list[set[str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag_name = tag.casefold()
        mapping = {str(key): str(value or "") for key, value in attrs}

        if self._card is None and "data-catalog-card" in mapping:
            self._card = _Card(attrs=mapping)
            self._depth = 1
            self._class_stack = [_classes(mapping)]
        elif self._card is not None and tag_name not in _VOID_TAGS:
            self._depth += 1
            self._class_stack.append(_classes(mapping))

        if self._card is None:
            return
        if tag_name == "a":
            href = mapping.get("href", "").strip()
            if href:
                self._card.links.append(urljoin(self.base_url, href))
        elif tag_name == "img":
            if not self._card.name:
                self._card.name = mapping.get("alt", "").strip()
            if not self._card.image_src:
                self._card.image_src = urljoin(
                    self.base_url,
                    mapping.get("src", "").strip(),
                )

    def handle_endtag(self, tag: str) -> None:
        if self._card is None or tag.casefold() in _VOID_TAGS:
            return
        self._depth -= 1
        if self._class_stack:
            self._class_stack.pop()
        if self._depth == 0:
            self.cards.append(self._card)
            self._card = None
            self._class_stack = []

    def handle_data(self, data: str) -> None:
        if self._card is None:
            return
        text = " ".join(str(data).split())
        if not text:
            return
        self._card.all_text.append(text)
        if not self._class_stack:
            return
        for class_name in self._class_stack[-1]:
            self._card.class_text.setdefault(class_name, []).append(text)


def fetch_catalog_html(
    url: str = BGAMING_SLOTS_URL,
    *,
    timeout_s: float = 30.0,
) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/136 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=max(1.0, float(timeout_s))) as response:
        return response.read().decode("utf-8", errors="replace")



def crawl_catalog(
    *,
    catalog_url: str = BGAMING_SLOTS_URL,
    search_url: str = BGAMING_CATALOG_SEARCH_URL,
    max_pages: int = 100,
    timeout_s: float = 30.0,
) -> CatalogCrawlResult:
    limit = max(1, int(max_pages))
    diagnostics: list[str] = []
    by_slug: dict[str, BGamingCatalogRecord] = {}

    first_html = fetch_catalog_html(catalog_url, timeout_s=timeout_s)
    first_raw = parse_catalog_html(first_html, base_url=catalog_url)
    first, _rejected = filter_records_by_game_type(first_raw, "Slots")
    if not first_raw:
        raise ValueError("BGaming initial catalog did not expose data-catalog-card records.")
    if not first:
        raise ValueError("BGaming initial catalog did not expose valid Slots records.")
    _merge_catalog_records(by_slug, first)

    if limit == 1:
        diagnostics.append("crawl limited to one page")
        return CatalogCrawlResult(
            records=tuple(_sorted_records(by_slug)),
            pages=1,
            authoritative=False,
            diagnostics=tuple(diagnostics),
        )

    page = 2
    has_more = True
    expected_total_pages: int | None = None
    authoritative = True

    while has_more and page <= limit:
        try:
            payload = _fetch_catalog_page(
                search_url,
                page=page,
                timeout_s=timeout_s,
            )
        except (OSError, TimeoutError, ValueError) as exc:
            authoritative = False
            diagnostics.append(
                f"page {page} failed: {type(exc).__name__}"
            )
            break

        reported_page = _as_positive_int(payload.get("page")) or page
        if reported_page != page:
            authoritative = False
            diagnostics.append(
                f"unexpected page: requested={page}, reported={reported_page}"
            )
            break

        reported_total = _as_positive_int(payload.get("total"))
        if expected_total_pages is None:
            expected_total_pages = reported_total
        elif (
            reported_total is not None
            and reported_total != expected_total_pages
        ):
            authoritative = False
            diagnostics.append(
                "REST total changed during crawl: "
                f"{expected_total_pages}->{reported_total}"
            )
            break

        html = str(payload.get("html") or "")
        raw_records = parse_catalog_html(html, base_url=catalog_url)
        records, _rejected = filter_records_by_game_type(raw_records, "Slots")
        _merge_catalog_records(by_slug, records)

        has_more = bool(payload.get("hasMore"))
        if has_more and not raw_records:
            authoritative = False
            diagnostics.append(f"page {page} empty while hasMore=true")
            break
        page += 1

    terminal_page = page - 1
    if has_more and page > limit:
        authoritative = False
        diagnostics.append(f"crawl limited to {limit} pages")
    if (
        not has_more
        and expected_total_pages is not None
        and terminal_page != expected_total_pages
    ):
        authoritative = False
        diagnostics.append(
            "terminal page does not match REST total: "
            f"terminal={terminal_page}, total={expected_total_pages}"
        )

    return CatalogCrawlResult(
        records=tuple(_sorted_records(by_slug)),
        pages=terminal_page,
        authoritative=authoritative,
        diagnostics=tuple(diagnostics),
    )


def catalog_crawl_json(result: CatalogCrawlResult) -> str:
    return json.dumps(
        result.to_dict(),
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def _fetch_catalog_page(
    url: str,
    *,
    page: int,
    timeout_s: float,
) -> dict[str, Any]:
    params = {
        "sort": "release_date",
        "order": "DESC",
        "posts_per_page": 25,
        "format": "html",
        "columns_style": 1,
        "game_type": 1,
        "game_label": 1,
        "most_popular": 0,
        "ver": 105,
        "filter": "game",
        "page": int(page),
        "lang": "en",
    }
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/136 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=max(1.0, float(timeout_s))) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise TypeError("BGaming catalog REST response is not an object.")
    return payload


def _merge_catalog_records(
    target: dict[str, BGamingCatalogRecord],
    records: list[BGamingCatalogRecord],
) -> None:
    for item in records:
        target.setdefault(item.slug, item)


def _sorted_records(
    records: dict[str, BGamingCatalogRecord],
) -> list[BGamingCatalogRecord]:
    return sorted(
        records.values(),
        key=lambda item: (item.name.casefold(), item.slug),
    )


def _as_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_catalog_html(
    html: str,
    *,
    base_url: str = BGAMING_SLOTS_URL,
) -> list[BGamingCatalogRecord]:
    parser = _CatalogParser(base_url)
    parser.feed(html or "")

    records: list[BGamingCatalogRecord] = []
    seen: set[str] = set()
    for card in parser.cards:
        public_url = _public_url(card.links)
        slug = _slug_from_public_url(public_url)
        if not slug or slug in seen:
            continue

        name = card.name or _first_class_text(card, "heading-35")
        if not name:
            continue

        demo_url = _demo_url(card.links)
        identifier = _identifier_from_demo_url(demo_url)
        ephemeral = _has_ephemeral_credential(demo_url)
        text = " ".join(card.all_text)
        coming_soon = _coming_soon(text)

        if ephemeral:
            availability = "EPHEMERAL_DEMO"
            execution_url = _stable_ephemeral_execution_url(
                demo_url,
                identifier,
            ) or public_url
            safe_demo = ""
        elif demo_url:
            availability = "DEMO"
            execution_url = demo_url
            safe_demo = demo_url
        elif coming_soon:
            availability = "COMING_SOON"
            execution_url = public_url
            safe_demo = ""
        else:
            availability = "NO_DEMO"
            execution_url = public_url
            safe_demo = ""

        thumbnail = card.attrs.get("data-image", "").strip() or card.image_src
        records.append(
            BGamingCatalogRecord(
                provider="bgaming",
                slug=slug,
                name=name,
                public_url=public_url,
                execution_url=execution_url,
                demo_url=safe_demo,
                thumbnail_url=thumbnail,
                identifier=identifier,
                rtp=_rtp(text),
                volatility=_first_class_text(card, "paragraph-98"),
                game_type=_first_class_text(card, "game-type-text"),
                availability=availability,
            )
        )
        seen.add(slug)
    return records


def filter_records_by_game_type(
    records: list[BGamingCatalogRecord],
    expected: str,
) -> tuple[list[BGamingCatalogRecord], list[BGamingCatalogRecord]]:
    target = str(expected or "").strip().casefold()
    if not target:
        return list(records), []
    accepted = [
        item
        for item in records
        if item.game_type.strip().casefold() == target
    ]
    rejected = [item for item in records if item not in accepted]
    return accepted, rejected


def catalog_json(records: list[BGamingCatalogRecord]) -> str:
    return json.dumps(
        [item.to_dict() for item in records],
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def _classes(attrs: dict[str, str]) -> set[str]:
    return {
        item
        for item in attrs.get("class", "").split()
        if item
    }


def _first_class_text(card: _Card, class_name: str) -> str:
    return " ".join(card.class_text.get(class_name, [])).strip()


def _public_url(links: list[str]) -> str:
    for link in links:
        parts = urlsplit(link)
        path = parts.path.casefold()
        if "/games/" in path and "bgaming-network.com" not in (parts.hostname or ""):
            return link
    return ""


def _demo_url(links: list[str]) -> str:
    for link in links:
        parts = urlsplit(link)
        host = (parts.hostname or "").casefold()
        if not (host == "bgaming-network.com" or host.endswith(".bgaming-network.com")):
            continue
        path = parts.path.casefold()
        if "/play/" in path or "/games/" in path or path.rstrip("/").endswith("/hyperhive"):
            return link
    return ""


def _slug_from_public_url(url: str) -> str:
    parts = [part for part in urlsplit(url).path.split("/") if part]
    lowered = [part.casefold() for part in parts]
    if "games" not in lowered:
        return ""
    index = lowered.index("games")
    return parts[index + 1].casefold() if index + 1 < len(parts) else ""


def _identifier_from_demo_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.split("/") if part]
    lowered = [part.casefold() for part in parts]
    for marker in ("play", "games"):
        if marker not in lowered:
            continue
        index = lowered.index(marker)
        if index + 1 < len(parts):
            return parts[index + 1]
    query = parse_qs(parsed.query)
    for key in ("game", "identifier"):
        values = query.get(key)
        if values:
            return str(values[0])
    return ""


def resolve_catalog_execution_url(
    source: str,
    *,
    timeout_s: float = 30.0,
    max_pages: int = 100,
) -> str:
    parsed = urlsplit(str(source or ""))
    slug = _slug_from_public_url(
        parsed._replace(query="", fragment="").geturl()
    )
    if not slug:
        return str(source or "")

    result = crawl_catalog(
        max_pages=max_pages,
        timeout_s=timeout_s,
    )
    for item in result.records:
        if item.slug == slug:
            return item.execution_url or item.public_url
    return str(source or "")


def _stable_ephemeral_execution_url(
    demo_url: str,
    identifier: str,
) -> str:
    if not demo_url or not identifier:
        return ""
    parsed = urlsplit(demo_url)
    if parsed.path.casefold().rstrip("/").endswith("/hyperhive"):
        return ""
    host = (parsed.hostname or "").casefold()
    if not (
        host == "bgaming-network.com"
        or host.endswith(".bgaming-network.com")
    ):
        return ""
    return (
        f"{parsed.scheme or 'https'}://{parsed.netloc}"
        f"/play/{identifier}/FUN"
    )


def _has_ephemeral_credential(url: str) -> bool:
    if not url:
        return False
    query = parse_qs(urlsplit(url).query, keep_blank_values=False)
    return any(
        key.casefold() in {"launch_token", "play_token", "token"}
        for key in query
    )


def _coming_soon(text: str) -> bool:
    lowered = text.casefold()
    return any(
        marker in lowered
        for marker in ("coming soon", "próximamente", "em breve")
    )


def _rtp(text: str) -> float | None:
    match = re.search(r"\brtp\s*([0-9]+(?:\.[0-9]+)?)\s*%", text, re.IGNORECASE)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None
