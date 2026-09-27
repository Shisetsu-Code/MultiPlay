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
    request_start: int = 0
    request_end: int = 0
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

        for _round in range(4):
            advanced = False
            for frame in page.frames:
                try:
                    result = frame.evaluate(
                        _CALL_CONTROL_JS,
                        {"control": "__multiplay_advance_only__"},
                    )
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(result, dict) and result.get("advanced"):
                    advanced = True
                    page.wait_for_timeout(1200)
                    break
            if not advanced:
                break

        for route in routes:
            route_id = str(route.get("route_id") or "")
            control = str(route.get("control") or "").strip()
            handler = str(route.get("handler") or "").strip()
            spec = _parse_handler(handler)
            if spec is None and not control:
                outcomes.append(
                    HandlerProbeOutcome(
                        route_id=route_id,
                        handler=handler,
                        called=False,
                        error="no executable control or handler",
                    )
                )
                continue

            paths, args = spec if spec is not None else ([], [])
            called = False
            last_error = ""
            resolved_path = ""
            resolved_frame = ""
            route_http_start = len(captured_http)
            capture_state["active"] = True

            for attempt in range(3):
                attempt_called = False
                for frame in page.frames:
                    result = None
                    if control and not paths:
                        for _advance in range(3):
                            try:
                                result = frame.evaluate(
                                    _CALL_CONTROL_JS,
                                    {"control": control},
                                )
                            except Exception as exc:  # noqa: BLE001
                                last_error = f"{type(exc).__name__}: {exc}"
                                break
                            if isinstance(result, dict) and result.get("advanced"):
                                page.wait_for_timeout(1200)
                                continue
                            break

                    if (
                        (not isinstance(result, dict) or not result.get("called"))
                        and paths
                    ):
                        try:
                            result = frame.evaluate(
                                _CALL_HANDLER_JS,
                                {"paths": paths, "args": args, "handler": handler},
                            )
                        except Exception as exc:  # noqa: BLE001
                            last_error = f"{type(exc).__name__}: {exc}"
                            continue

                    if not isinstance(result, dict):
                        continue
                    if result.get("called"):
                        called = True
                        attempt_called = True
                        resolved_path = str(result.get("path") or "")
                        resolved_frame = _safe_frame_url(frame.url)
                        page.wait_for_timeout(max(250, int(after_call_ms)))
                        break
                    if result.get("error"):
                        last_error = str(result["error"])

                if not attempt_called:
                    continue

                route_http = captured_http[route_http_start:]
                if any(not _is_init_exchange(item) for item in route_http):
                    break

                if attempt < 2:
                    page.wait_for_timeout(1200)

            capture_state["active"] = False
            if called:
                outcomes.append(
                    HandlerProbeOutcome(
                        route_id=route_id,
                        handler=handler,
                        called=True,
                        resolved_path=resolved_path,
                        frame_url=resolved_frame,
                        request_start=route_http_start,
                        request_end=len(captured_http),
                    )
                )

            if not called:
                capture_state["active"] = False
                outcomes.append(
                    HandlerProbeOutcome(
                        route_id=route_id,
                        handler=handler,
                        called=False,
                        request_start=route_http_start,
                        request_end=len(captured_http),
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


def _is_init_exchange(exchange: HttpExchange) -> bool:
    body = exchange.request_body
    if not isinstance(body, dict):
        return False
    return (
        str(body.get("command") or "").casefold() == "init"
        or str(body.get("method") or "").casefold() == "init"
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


_CALL_CONTROL_JS = """
({control}) => {
  const getRequire = () => {
    try {
      const chunks = globalThis.webpackChunk;
      if (!chunks || typeof chunks.push !== "function") return null;
      let req = null;
      const chunkId = 900000000 + Math.floor(Math.random() * 90000000);
      chunks.push([[chunkId], {}, (runtime) => { req = runtime; }]);
      return req;
    } catch (_error) {
      return null;
    }
  };

  const runtime = getRequire();
  if (!runtime || !runtime.m) {
    return {called: false, error: "webpack runtime not found"};
  }

  const ids = Object.keys(runtime.m)
    .map((id) => {
      let source = "";
      try { source = Function.prototype.toString.call(runtime.m[id]); } catch (_error) {}
      let score = 0;
      if (source.includes("currentScene")) score += 8;
      if (source.includes("casinoOptions")) score += 8;
      if (source.includes("showModal")) score += 4;
      if (source.includes("all")) score += 2;
      return {id, score};
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 40);

  const clickable = (node, depth = 0) => {
    if (!node || depth > 4) return null;
    try {
      if (typeof node._executeOnClick === "function") return node;
      if (typeof node.callClick === "function") return node;
      const children = Array.isArray(node.children) ? node.children : [];
      for (const child of children) {
        const found = clickable(child, depth + 1);
        if (found) return found;
      }
    } catch (_error) {}
    return null;
  };

  const execute = (game, name, moduleId) => {
    let all;
    try { all = game.all; } catch (_error) { return null; }
    if (!all || !all[name]) return null;
    const node = clickable(all[name]);
    if (!node) return null;
    const basePath = "webpack:" + moduleId + ".all[" + JSON.stringify(name) + "]";
    try {
      if (typeof node._executeOnClick === "function") {
        node._executeOnClick("invoke");
        return {called: true, path: basePath + "._executeOnClick"};
      }
      if (typeof node.callClick === "function") {
        node.callClick();
        return {called: true, path: basePath + ".callClick"};
      }
    } catch (error) {
      return {
        called: false,
        path: basePath,
        error: String(error && (error.stack || error.message || error)),
      };
    }
    return null;
  };

  for (const item of ids) {
    let exports;
    try { exports = runtime(item.id); } catch (_error) { continue; }
    const values = [exports];
    if (exports && (typeof exports === "object" || typeof exports === "function")) {
      for (const key of ["A", "default"]) {
        try { if (exports[key] != null) values.push(exports[key]); } catch (_error) {}
      }
      try { values.push(...Object.values(exports).slice(0, 20)); } catch (_error) {}
    }

    for (const value of values) {
      if (value == null) continue;
      if (typeof value !== "object" && typeof value !== "function") continue;

      const target = execute(value, control, item.id);
      if (target) return target;

      for (const starter of ["continue", "start-button", "start-btn", "play-button"]) {
        if (starter === control) continue;
        const advanced = execute(value, starter, item.id);
        if (advanced && advanced.called) {
          return {
            called: false,
            advanced: true,
            path: advanced.path,
          };
        }
      }
    }
  }

  return {called: false, error: "button object not found"};
}
"""

_CALL_HANDLER_JS = """
({paths, args, handler}) => {
  const errorText = (error) =>
    String(error && (error.stack || error.message || error));

  const webpackResolver = () => {
    const chunks = globalThis.webpackChunk;
    if (!chunks || typeof chunks.push !== "function") return null;

    let req = null;
    const chunkId =
      "multiplay-probe-" + Date.now() + "-" + Math.floor(Math.random() * 1e9);
    try {
      chunks.push([[chunkId], {}, (webpackRequire) => {
        req = webpackRequire;
      }]);
    } catch (_error) {
      return null;
    }
    if (typeof req !== "function") return null;

    try {
      const module = req(2260);
      const fn = module && (module.A || module.default);
      return typeof fn === "function" ? fn : null;
    } catch (_error) {
      return null;
    }
  };

  if (!String(handler || "").startsWith("this.")) {
    const resolver = webpackResolver();
    if (resolver) {
      try {
        resolver(handler, null);
        return {called: true, path: "webpack:2260"};
      } catch (error) {
        // Fall through to direct-path probing.
      }
    }
  }

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

  let lastError = "";
  for (const path of paths) {
    try {
      const resolved = resolvePath(path);
      if (!resolved) continue;
      Reflect.apply(resolved.fn, resolved.owner, args);
      return {called: true, path};
    } catch (error) {
      lastError = errorText(error);
    }
  }
  return {called: false, error: lastError || "not found"};
}
"""
