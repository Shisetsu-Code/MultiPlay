from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..evidence import redact

_SENSITIVE_QUERY_PARTS = {
    "authorization",
    "cookie",
    "csrf",
    "key",
    "password",
    "secret",
    "session",
    "token",
}


@dataclass(frozen=True, slots=True)
class ClickCandidate:
    source: str
    x: float
    y: float
    score: float
    label: str = ""
    frame_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["frame_url"] = _safe_url(self.frame_url)
        return data


@dataclass(frozen=True, slots=True)
class BrowserExploreResult:
    output_dir: Path
    har_path: Path
    trace_path: Path
    screenshots: tuple[Path, ...]
    stateful_effects: int
    clicks_attempted: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "har_path": str(self.har_path),
            "trace_path": str(self.trace_path),
            "screenshots": [str(item) for item in self.screenshots],
            "stateful_effects": self.stateful_effects,
            "clicks_attempted": self.clicks_attempted,
        }


def explore_browser(
    *,
    url: str,
    output_dir: str | Path,
    max_clicks: int = 24,
    settle_ms: int = 3500,
    after_click_ms: int = 1400,
    headless: bool = True,
    viewport: tuple[int, int] = (1440, 900),
) -> BrowserExploreResult:
    """Discover current controls and correlate each real click with network effects."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install MultiPlay with the 'browser' extra") from exc

    target = str(url or "").strip()
    if not target:
        raise ValueError("browser exploration URL is empty")

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    shots = root / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    har_path = root / "browser.har"
    trace_path = root / "trace.json"

    events: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    screenshots: list[Path] = []
    max_clicks = max(1, int(max_clicks))
    settle_ms = max(250, int(settle_ms))
    after_click_ms = max(250, int(after_click_ms))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=bool(headless))
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            device_scale_factor=1,
            record_har_path=str(har_path),
            record_har_content="embed",
            record_har_mode="full",
        )

        attached_pages: set[int] = set()

        def attach_page(page) -> None:
            key = id(page)
            if key in attached_pages:
                return
            attached_pages.add(key)
            page.on("request", lambda request: _record_request(events, request))
            page.on("response", lambda response: _record_response(events, response))
            page.on("websocket", lambda websocket: _record_websocket(events, websocket))

        context.on("page", attach_page)
        page = context.new_page()
        attach_page(page)
        page.goto(target, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(settle_ms)

        state_epoch = 0
        seen: set[tuple[int, int, int, str]] = set()

        baseline = page.screenshot(full_page=False, type="jpeg", quality=65)
        baseline_path = shots / "000-baseline.jpg"
        baseline_path.write_bytes(baseline)
        screenshots.append(baseline_path)

        for click_index in range(1, max_clicks + 1):
            if page.is_closed():
                break

            before = page.screenshot(full_page=False, type="jpeg", quality=65)
            candidates = discover_click_candidates(page, before)
            candidate = _next_candidate(candidates, seen, state_epoch)
            if candidate is None:
                break

            seen.add(_candidate_key(candidate, state_epoch))
            start_event = len(events)
            before_url = page.url
            error = ""

            try:
                page.mouse.click(candidate.x, candidate.y)
                page.wait_for_timeout(after_click_ms)
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"

            after = (
                before
                if page.is_closed()
                else page.screenshot(full_page=False, type="jpeg", quality=65)
            )
            shot_path = shots / f"{click_index:03d}-after.jpg"
            shot_path.write_bytes(after)
            screenshots.append(shot_path)

            causal = events[start_event:]
            productive = [event for event in causal if event_is_stateful(event)]
            changed = image_change_ratio(before, after)
            if productive or page.url != before_url:
                state_epoch += 1

            signatures = sorted(
                {
                    event_signature(event)
                    for event in productive
                    if event_signature(event)
                }
            )
            actions.append(
                {
                    "index": click_index,
                    "state_epoch": state_epoch,
                    "candidate": candidate.to_dict(),
                    "page_url_before": _safe_url(before_url),
                    "page_url_after": _safe_url(
                        page.url if not page.is_closed() else before_url
                    ),
                    "image_change_ratio": round(changed, 6),
                    "stateful_event_count": len(productive),
                    "effect_signatures": signatures,
                    "events": _causal_events(causal, productive),
                    "error": error,
                }
            )

        context.close()
        browser.close()

    trace = {
        "schema": "multiplay/browser-causal/v1",
        "start_url": _safe_url(target),
        "max_clicks": max_clicks,
        "clicks_attempted": len(actions),
        "stateful_effects": sum(item["stateful_event_count"] for item in actions),
        "actions": actions,
        "all_event_count": len(events),
    }
    trace_path.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return BrowserExploreResult(
        output_dir=root,
        har_path=har_path,
        trace_path=trace_path,
        screenshots=tuple(screenshots),
        stateful_effects=int(trace["stateful_effects"]),
        clicks_attempted=len(actions),
    )


def discover_click_candidates(page, screenshot_bytes: bytes) -> list[ClickCandidate]:
    dom = _dom_candidates(page)
    canvas_regions = _canvas_regions(page)
    viewport = page.viewport_size or {"width": 1440, "height": 900}
    visual = visual_candidates_from_screenshot(
        screenshot_bytes,
        canvas_regions
        or [(0.0, 0.0, float(viewport["width"]), float(viewport["height"]))],
        max_points=28,
    )
    combined = [*dom, *visual]
    combined.sort(
        key=lambda item: (1 if item.source == "dom" else 0, item.score),
        reverse=True,
    )
    return _dedupe_candidates(combined)


def visual_candidates_from_screenshot(
    image_bytes: bytes,
    regions: list[tuple[float, float, float, float]],
    *,
    max_points: int = 28,
) -> list[ClickCandidate]:
    """Rank high-contrast cells from the current screenshot; no OCR or named controls."""
    try:
        from PIL import Image, ImageFilter, ImageStat
    except ImportError as exc:
        raise RuntimeError("Install MultiPlay with the 'browser' extra") from exc

    image = Image.open(io.BytesIO(image_bytes)).convert("L")
    edges = image.filter(ImageFilter.FIND_EDGES)
    width, height = image.size
    rows: list[ClickCandidate] = []

    for rx, ry, rw, rh in regions:
        x0 = max(0, min(width - 1, int(rx)))
        y0 = max(0, min(height - 1, int(ry)))
        x1 = max(x0 + 1, min(width, int(rx + rw)))
        y1 = max(y0 + 1, min(height, int(ry + rh)))
        region_width = x1 - x0
        region_height = y1 - y0
        if region_width < 32 or region_height < 32:
            continue

        columns = max(3, min(14, region_width // 72))
        row_count = max(3, min(10, region_height // 72))
        cell_w = region_width / columns
        cell_h = region_height / row_count

        for row in range(row_count):
            for column in range(columns):
                cx0 = int(x0 + column * cell_w)
                cy0 = int(y0 + row * cell_h)
                cx1 = int(x0 + (column + 1) * cell_w)
                cy1 = int(y0 + (row + 1) * cell_h)
                if cx1 <= cx0 or cy1 <= cy0:
                    continue
                edge_mean = float(
                    ImageStat.Stat(edges.crop((cx0, cy0, cx1, cy1))).mean[0]
                )
                gray_std = float(
                    ImageStat.Stat(image.crop((cx0, cy0, cx1, cy1))).stddev[0]
                )
                rows.append(
                    ClickCandidate(
                        source="visual",
                        x=(cx0 + cx1) / 2,
                        y=(cy0 + cy1) / 2,
                        score=edge_mean + gray_std * 0.65,
                        label="visual-cell",
                    )
                )

    rows.sort(key=lambda item: item.score, reverse=True)
    selected: list[ClickCandidate] = []
    for item in rows:
        if any(_distance(item, old) < 42 for old in selected):
            continue
        selected.append(item)
        if len(selected) >= max(1, int(max_points)):
            break
    return selected


def event_is_stateful(event: dict[str, Any]) -> bool:
    kind = str(event.get("kind") or "")
    if kind == "websocket_sent":
        return True
    if kind != "http_request":
        return False
    return str(event.get("method") or "").upper() not in {"", "GET", "HEAD", "OPTIONS"}


def event_signature(event: dict[str, Any]) -> str:
    kind = str(event.get("kind") or "")
    if kind == "websocket_sent":
        return "WS " + _url_path(str(event.get("url") or ""))
    if kind == "http_request":
        method = str(event.get("method") or "").upper()
        return f"{method} {_url_path(str(event.get('url') or ''))}"
    return ""


def image_change_ratio(left: bytes, right: bytes) -> float:
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError:
        return 0.0
    a = Image.open(io.BytesIO(left)).convert("RGB")
    b = Image.open(io.BytesIO(right)).convert("RGB")
    if a.size != b.size:
        return 1.0
    means = ImageStat.Stat(ImageChops.difference(a, b)).mean
    return sum(float(item) for item in means) / (255.0 * len(means))


def _dom_candidates(page) -> list[ClickCandidate]:
    selector = (
        "button, [role='button'], input[type='button'], input[type='submit'], "
        "a[href], [onclick]"
    )
    rows: list[ClickCandidate] = []
    for frame in page.frames:
        try:
            handles = frame.query_selector_all(selector)
        except Exception:  # noqa: BLE001
            handles = []
        for handle in handles[:120]:
            box = None
            data = {}
            try:
                box = handle.bounding_box()
                if not box or box["width"] < 8 or box["height"] < 8:
                    continue
                data = handle.evaluate(
                    """(el) => ({
                        tag: el.tagName || '',
                        role: el.getAttribute('role') || '',
                        label: el.getAttribute('aria-label') || '',
                        text: (el.innerText || el.value || '').trim().slice(0, 120)
                    })"""
                )
            except Exception:  # noqa: BLE001
                box = None
            if not box:
                continue
            label = " ".join(
                value
                for value in (
                    str(data.get("tag") or "").lower(),
                    str(data.get("role") or ""),
                    str(data.get("label") or ""),
                    str(data.get("text") or ""),
                )
                if value
            )
            rows.append(
                ClickCandidate(
                    source="dom",
                    x=float(box["x"] + box["width"] / 2),
                    y=float(box["y"] + box["height"] / 2),
                    score=1000.0,
                    label=label,
                    frame_url=frame.url,
                )
            )
    return rows


def _canvas_regions(page) -> list[tuple[float, float, float, float]]:
    rows: list[tuple[float, float, float, float]] = []
    for frame in page.frames:
        try:
            handles = frame.query_selector_all("canvas")
        except Exception:  # noqa: BLE001
            handles = []
        for handle in handles:
            try:
                box = handle.bounding_box()
            except Exception:  # noqa: BLE001
                box = None
            if not box or box["width"] < 64 or box["height"] < 64:
                continue
            rows.append(
                (
                    float(box["x"]),
                    float(box["y"]),
                    float(box["width"]),
                    float(box["height"]),
                )
            )
    return rows


def _next_candidate(
    candidates: list[ClickCandidate],
    seen: set[tuple[int, int, int, str]],
    state_epoch: int,
) -> ClickCandidate | None:
    return next(
        (
            candidate
            for candidate in candidates
            if _candidate_key(candidate, state_epoch) not in seen
        ),
        None,
    )


def _candidate_key(candidate: ClickCandidate, state_epoch: int) -> tuple[int, int, int, str]:
    epoch = -1 if candidate.source == "dom" else int(state_epoch)
    identity = candidate.source
    if candidate.source == "dom" and candidate.label:
        identity += ":" + candidate.label[:80]
    return (
        epoch,
        round(candidate.x / 10.0),
        round(candidate.y / 10.0),
        identity,
    )


def _dedupe_candidates(values: list[ClickCandidate]) -> list[ClickCandidate]:
    out: list[ClickCandidate] = []
    for item in values:
        if any(_distance(item, seen) < 12 for seen in out):
            continue
        out.append(item)
    return out


def _distance(left: ClickCandidate, right: ClickCandidate) -> float:
    return ((left.x - right.x) ** 2 + (left.y - right.y) ** 2) ** 0.5


def _record_request(events: list[dict[str, Any]], request) -> None:
    events.append(
        {
            "kind": "http_request",
            "method": request.method,
            "url": _safe_url(request.url),
            "resource_type": request.resource_type,
            "body": _safe_payload(request.post_data),
        }
    )


def _record_response(events: list[dict[str, Any]], response) -> None:
    events.append(
        {
            "kind": "http_response",
            "method": response.request.method,
            "url": _safe_url(response.url),
            "status": int(response.status),
        }
    )


def _record_websocket(events: list[dict[str, Any]], websocket) -> None:
    safe = _safe_url(websocket.url)
    websocket.on(
        "framesent",
        lambda payload: events.append(
            {"kind": "websocket_sent", "url": safe, "payload": _safe_payload(payload)}
        ),
    )
    websocket.on(
        "framereceived",
        lambda payload: events.append(
            {
                "kind": "websocket_received",
                "url": safe,
                "payload": _safe_payload(payload),
            }
        ),
    )



def _causal_events(
    causal: list[dict[str, Any]],
    productive: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not productive:
        return []

    http_urls = {
        str(event.get("url") or "")
        for event in productive
        if event.get("kind") == "http_request"
    }
    websocket_urls = {
        str(event.get("url") or "")
        for event in productive
        if event.get("kind") == "websocket_sent"
    }
    return [
        event
        for event in causal
        if event_is_stateful(event)
        or (
            event.get("kind") == "http_response"
            and str(event.get("url") or "") in http_urls
        )
        or (
            event.get("kind") == "websocket_received"
            and str(event.get("url") or "") in websocket_urls
        )
    ]


def _safe_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value[:8192].decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return redact(value)

    text = value[:8192]
    try:
        return redact(json.loads(text))
    except json.JSONDecodeError:
        pairs = parse_qsl(text, keep_blank_values=True)
        if pairs and "=" in text:
            return redact({key: item for key, item in pairs})
        return text


def _safe_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.casefold()
        safe = (
            "<redacted>"
            if any(marker in lowered for marker in _SENSITIVE_QUERY_PARTS)
            else value
        )
        pairs.append((key, safe))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs, doseq=True), "")
    )


def _url_path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}"
