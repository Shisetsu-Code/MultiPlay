from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ...models import EvidenceBundle, HttpExchange

_HANDLER_RE = re.compile(
    r"^\s*([A-Za-z_$][A-Za-z0-9_$-]*(?:\.[A-Za-z_$][A-Za-z0-9_$-]*)*)"
    r"(?:\x60(.*))?\s*$"
)


@dataclass(frozen=True, slots=True)
class HandlerProbeOutcome:
    route_id: str
    handler: str
    called: bool
    resolved_path: str = ""
    frame_url: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HandlerProbeResult:
    evidence: EvidenceBundle
    outcomes: tuple[HandlerProbeOutcome, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcomes": [item.to_dict() for item in self.outcomes],
        }


def probe_bgaming_handlers(
    url: str,
    routes: list[dict[str, Any]],
    *,
    har_path: str | Path,
    settle_ms: int = 12_000,
    after_call_ms: int = 2_000,
) -> HandlerProbeResult:
    """Call already-discovered game handlers without clicking coordinates."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install MultiPlay with the 'browser' extra") from exc

    target = str(url or "").strip()
    if not target:
        raise ValueError("handler probe URL is empty")

    har = Path(har_path)
    har.parent.mkdir(parents=True, exist_ok=True)
    outcomes: list[HandlerProbeOutcome] = []
    captured_http: list[HttpExchange] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
            record_har_path=str(har),
            record_har_content="embed",
            record_har_mode="full",
        )
        page = context.new_page()
        capture_state = {"active": False}

        def capture_response(response: Any) -> None:
            if not capture_state["active"]:
                return
            request = response.request
            method = str(request.method or "").upper()
            if method in {"GET", "HEAD", "OPTIONS"}:
                return

            body: Any = None
            raw = request.post_data
            if raw:
                try:
                    body = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    body = raw

            captured_http.append(
                HttpExchange(
                    evidence_id=f"handler:{len(captured_http)}",
                    method=method,
                    url=str(request.url),
                    request_body=body,
                    response_status=int(response.status),
                )
            )

        page.on("response", capture_response)
        page.goto(target, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(max(1000, int(settle_ms)))

        for route in routes:
            route_id = str(route.get("route_id") or "")
            handler = str(route.get("handler") or "").strip()
            spec = _parse_handler(handler)
            if spec is None:
                outcomes.append(
                    HandlerProbeOutcome(
                        route_id=route_id,
                        handler=handler,
                        called=False,
                        error="unsupported handler expression",
                    )
                )
                continue

            paths, args = spec
            called = False
            last_error = ""
            capture_state["active"] = True
            for frame in page.frames:
                try:
                    result = frame.evaluate(
                        _CALL_HANDLER_JS,
                        {"paths": paths, "args": args},
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = f"{type(exc).__name__}: {exc}"
                    continue

                if not isinstance(result, dict):
                    continue
                if result.get("called"):
                    outcomes.append(
                        HandlerProbeOutcome(
                            route_id=route_id,
                            handler=handler,
                            called=True,
                            resolved_path=str(result.get("path") or ""),
                            frame_url=_safe_frame_url(frame.url),
                        )
                    )
                    called = True
                    page.wait_for_timeout(max(250, int(after_call_ms)))
                    capture_state["active"] = False
                    break
                if result.get("error"):
                    last_error = str(result["error"])

            if not called:
                capture_state["active"] = False
                outcomes.append(
                    HandlerProbeOutcome(
                        route_id=route_id,
                        handler=handler,
                        called=False,
                        error=last_error or "handler not found in loaded frames",
                    )
                )

        context.close()
        browser.close()

    return HandlerProbeResult(
        evidence=EvidenceBundle(
            http=captured_http,
            metadata={"source": "bgaming-handler-probe"},
        ),
        outcomes=tuple(outcomes),
    )


def _parse_handler(handler: str) -> tuple[list[str], list[Any]] | None:
    match = _HANDLER_RE.fullmatch(str(handler or ""))
    if match is None:
        return None

    path = str(match.group(1))
    raw_args = str(match.group(2) or "").strip()
    args = _parse_args(raw_args)

    paths = [path]
    if path.startswith("currentScene."):
        paths.append("game." + path)
        paths.append("data.game." + path)
    elif path.startswith("data.game."):
        paths.append(path.removeprefix("data."))
    elif path.startswith("game.currentScene."):
        paths.append(path.removeprefix("game."))

    return list(dict.fromkeys(paths)), args


def _parse_args(raw: str) -> list[Any]:
    if not raw:
        return []
    values = []
    for token in raw.split(","):
        text = token.strip()
        if not text:
            continue
        try:
            values.append(json.loads(text))
            continue
        except json.JSONDecodeError:
            pass
        lowered = text.casefold()
        if lowered == "true":
            values.append(True)
        elif lowered == "false":
            values.append(False)
        elif lowered == "null":
            values.append(None)
        else:
            values.append(text)
    return values


def _safe_frame_url(url: str) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(str(url or ""))
    return parts._replace(query="", fragment="").geturl()


_CALL_HANDLER_JS = """
({paths, args}) => {
  const resolvePath = (path) => {
    const parts = path.split(".");
    let owner = globalThis;
    for (let i = 0; i < parts.length - 1; i++) {
      if (owner == null) return null;
      owner = owner[parts[i]];
    }
    if (owner == null) return null;
    const key = parts[parts.length - 1];
    const fn = owner[key];
    if (typeof fn !== "function") return null;
    return {owner, fn};
  };

  for (const path of paths) {
    try {
      const resolved = resolvePath(path);
      if (!resolved) continue;
      Reflect.apply(resolved.fn, resolved.owner, args);
      return {called: true, path};
    } catch (error) {
      return {
        called: false,
        path,
        error: String(error && (error.stack || error.message || error)),
      };
    }
  }
  return {called: false, error: "not found"};
}
"""
