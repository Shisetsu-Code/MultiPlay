from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class BrowserAction:
    kind: Literal["click_selector", "click_xy", "wait"]
    selector: str | None = None
    x: float | None = None
    y: float | None = None
    timeout_ms: int = 1000


def capture_browser_evidence(
    *,
    url: str,
    har_path: str | Path,
    screenshot_path: str | Path | None = None,
    actions: list[BrowserAction] | None = None,
    viewport: tuple[int, int] = (1440, 900),
) -> None:
    """Acquire browser evidence without provider semantics.

    Playwright is intentionally optional. This layer may navigate/click/capture but it does
    not decide what a button means. Causal interpretation belongs to the provider analysis.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install MultiPlay with the 'browser' extra") from exc

    har_path = Path(har_path)
    har_path.parent.mkdir(parents=True, exist_ok=True)
    if screenshot_path is not None:
        Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            device_scale_factor=1,
            record_har_path=str(har_path),
            record_har_content="embed",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        for action in actions or []:
            if action.kind == "click_selector":
                if not action.selector:
                    raise ValueError("click_selector requires selector")
                page.locator(action.selector).click(timeout=action.timeout_ms)
            elif action.kind == "click_xy":
                if action.x is None or action.y is None:
                    raise ValueError("click_xy requires x and y")
                page.mouse.click(action.x, action.y)
            elif action.kind == "wait":
                page.wait_for_timeout(action.timeout_ms)
            else:
                raise ValueError(f"unsupported action: {action.kind}")
            page.wait_for_timeout(250)

        if screenshot_path is not None:
            page.screenshot(path=str(screenshot_path), full_page=False)

        context.close()
        browser.close()



def capture_interactive_har(
    *,
    url: str,
    har_path: str | Path,
    screenshot_path: str | Path | None = None,
    viewport: tuple[int, int] = (1440, 900),
) -> None:
    """Record a full headed browser session until the operator presses Enter.

    The operator may interact with canvas/WebGL/iframes normally. MultiPlay records
    the browser context HAR but makes no assumptions about provider controls.
    Raw HAR files may contain ephemeral credentials and therefore belong under
    gitignored local capture directories until ingested/redacted.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install MultiPlay with the 'browser' extra") from exc

    har_path = Path(har_path)
    har_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot = Path(screenshot_path) if screenshot_path is not None else None
    if screenshot is not None:
        screenshot.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            device_scale_factor=1,
            record_har_path=str(har_path),
            record_har_content="embed",
            record_har_mode="full",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        try:
            input(
                "Interact with the game in the opened browser. "
                "Press Enter here when the evidence capture is complete..."
            )
        except EOFError as exc:
            context.close()
            browser.close()
            raise RuntimeError(
                "Interactive capture requires an attached terminal."
            ) from exc

        if screenshot is not None and not page.is_closed():
            page.screenshot(path=str(screenshot), full_page=False)

        context.close()
        browser.close()
