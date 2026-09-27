from __future__ import annotations

import json
import secrets
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from ...action_graph import build_action_graph
from ...evidence import load_har, redact
from ...har_map import build_har_map
from .api_v2 import (
    ApiV2Template,
    apply_api_v2_template,
    choose_api_v2_template,
    extract_api_v2_templates,
)
from .bootstrap import extract_bootstrap_options, extract_window_options, sanitize_session_url
from .classify import API_V2, HYPERHIVE_JSONRPC, LEGACY_LINES, classify_bgaming
from .demo_spin import legacy_spin_options, resolve_base_bet
from .hyperhive import (
    HyperHiveTemplate,
    apply_hyperhive_template,
    choose_hyperhive_template,
    extract_hyperhive_templates,
)
from .hyperhive_demo import resolve_hyperhive_bet
from .probe import _allowed_source, _HttpSession, _is_hyperhive_url, _resolve_demo
from .wire import is_legacy_init


@dataclass(frozen=True, slots=True)
class DirectAction:
    action_id: str
    label: str
    kind: str
    wire_markers: tuple[str, ...]
    endpoint_ids: tuple[str, ...]
    executable: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "kind": self.kind,
            "wire_markers": list(self.wire_markers),
            "endpoint_ids": list(self.endpoint_ids),
            "executable": self.executable,
            "reason": self.reason,
        }


class BGamingDemoDirectSession:
    """Fresh in-memory BGaming demo session backed by an observed HAR contract."""

    def __init__(
        self,
        *,
        har_path: str | Path,
        url: str,
        timeout_s: float = 30.0,
    ) -> None:
        self.har_path = Path(har_path)
        self.url = str(url or "").strip()
        self.timeout_s = max(1.0, float(timeout_s))
        if not self.url or not _allowed_source(self.url):
            raise ValueError("BGaming direct session requires a BGaming URL.")
        _require_demo_intent(self.url)

        self.evidence = load_har(self.har_path)
        classifications = classify_bgaming(self.evidence)
        if not classifications:
            raise ValueError("HAR does not contain a recognized BGaming protocol family.")
        self.family = classifications[0].family
        if self.family not in {API_V2, LEGACY_LINES, HYPERHIVE_JSONRPC}:
            raise ValueError(
                f"direct demo execution is not implemented for family {self.family!r}"
            )

        self.report = build_har_map(self.har_path)
        self.graph = build_action_graph(self.har_path, include_all=True)
        self.http = _HttpSession()
        self.launch_url = ""
        self.endpoint_url = ""
        self.headers: dict[str, str] = {}
        self.round_series_id = int(time.time() * 1000)
        self.current_init: dict[str, Any] = {}
        self.default_bet: Any = None
        self.state_lock: Any = None
        self.token = ""
        self.rpc_id_sample: Any = 0
        self.api_templates: list[ApiV2Template] = []
        self.hyper_templates: list[HyperHiveTemplate] = []

    def open(self) -> dict[str, Any]:
        launch = _resolve_demo(self.http, self.url, timeout_s=self.timeout_s)
        self.launch_url = launch.url
        _require_demo_runtime(self.launch_url)

        if self.family == HYPERHIVE_JSONRPC:
            self._open_hyperhive(launch.text)
        else:
            self._open_classic(launch.text)

        return self.state()

    def state(self) -> dict[str, Any]:
        return {
            "provider": "bgaming",
            "environment": "demo",
            "family": self.family,
            "launch_url": sanitize_session_url(self.launch_url),
            "endpoint": sanitize_session_url(self.endpoint_url),
            "default_bet": self.default_bet,
            "has_state_lock": self.state_lock not in (None, ""),
            "actions": [item.to_dict() for item in self.actions()],
        }

    def actions(self) -> list[DirectAction]:
        rows: list[DirectAction] = []
        for action in self.report.get("actions", []):
            markers = tuple(str(item) for item in action.get("wire_markers") or [])
            endpoint_ids = tuple(str(item) for item in action.get("endpoint_ids") or [])
            executable, reason = self._can_execute(markers)
            rows.append(
                DirectAction(
                    action_id=str(action.get("action_id") or ""),
                    label=str(action.get("label") or ""),
                    kind=str(action.get("kind") or ""),
                    wire_markers=markers,
                    endpoint_ids=endpoint_ids,
                    executable=executable,
                    reason=reason,
                )
            )
        return rows

    def routes(self) -> list[dict[str, Any]]:
        executable_actions = {
            item.action_id: item
            for item in self.actions()
            if item.executable
        }
        out: list[dict[str, Any]] = []
        for route in self.graph.get("routes", []):
            item = dict(route)
            replay = str(item.get("replay_action_id") or "")
            item["executable"] = replay in executable_actions
            if replay and replay not in executable_actions:
                item["execution_reason"] = (
                    "matched replay shape is not executable in this session"
                )
            elif replay:
                item["execution_reason"] = ""
            else:
                item["execution_reason"] = (
                    "no demonstrated replay action linked to route"
                )
            out.append(item)
        return out

    def execute_route(
        self,
        route_id: str,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        route = next(
            (
                item
                for item in self.routes()
                if str(item.get("route_id") or "") == str(route_id)
            ),
            None,
        )
        if route is None:
            raise KeyError(f"unknown route_id: {route_id}")
        if not route.get("executable"):
            raise ValueError(
                str(route.get("execution_reason") or "route is not executable")
            )
        return self.execute(
            str(route.get("replay_action_id") or ""),
            overrides=overrides,
        )

    def execute(
        self,
        action_id: str,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected = next(
            (
                item
                for item in self.report.get("actions", [])
                if str(item.get("action_id") or "") == str(action_id)
            ),
            None,
        )
        if selected is None:
            raise KeyError(f"unknown action_id: {action_id}")

        markers = tuple(str(item) for item in selected.get("wire_markers") or [])
        executable, reason = self._can_execute(markers)
        if not executable:
            raise ValueError(reason)

        values = dict(overrides or {})
        if self.family == HYPERHIVE_JSONRPC:
            return self._execute_hyperhive(markers, values)
        return self._execute_classic(markers, values)

    def execute_inferred_api_v2_purchase(
        self,
        markers: tuple[str, ...] | list[str],
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate one statically resolved API-v2 purchase on a fresh demo session."""
        if self.family != API_V2:
            raise ValueError("inferred API-v2 purchase requires an API-v2 session")

        normalized = tuple(str(item) for item in markers)
        marker_map = _marker_map(normalized)
        features = _marker_values(normalized, "purchased_feature")
        if len(features) != 1:
            raise ValueError(
                "inferred API-v2 purchase requires exactly one purchased_feature"
            )
        purchased_feature = features[0]

        base = choose_api_v2_template(
            self.api_templates,
            command="spin",
        )
        if base is None:
            raise ValueError("no unique successful base spin template")

        values = dict(overrides or {})
        payload = apply_api_v2_template(
            base,
            fresh_options=self._fresh_api_options(base, values),
            fresh_extra_data=self._fresh_api_extra(base, values),
        )
        # Keep the command from the observed successful base-spin template.
        # Static call-graph resolution can encounter unrelated same-named
        # playGame implementations and must not overwrite demonstrated wire.
        options = payload.get("options")
        if not isinstance(options, dict):
            raise TypeError("base spin template has no options object")

        options["purchased_feature"] = purchased_feature
        level = str(marker_map.get("purchased_feature_level") or "").strip()
        if level:
            # Current BGaming API-v2 clients serialize purchase levels as strings.
            options["purchased_feature_level"] = level

        result = self.http.post_json(
            self.endpoint_url,
            payload,
            timeout_s=self.timeout_s,
            headers=self.headers,
            allow_http_error=True,
        )
        response = _json_value(result.text)
        success = 200 <= result.status < 400 and not (
            isinstance(response, dict)
            and response.get("error") not in (None, {}, [])
        )
        return {
            "status": result.status,
            "success": success,
            "endpoint": sanitize_session_url(self.endpoint_url),
            "request": redact(payload),
            "response": redact(response),
        }

    def execute_inferred_hyperhive(
        self,
        markers: tuple[str, ...] | list[str],
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a statically resolved HyperHive play shape in a fresh demo session.

        This path is intentionally narrow: the route must explicitly resolve to
        method=play, and only demonstrated request fields encoded in route markers
        are added to req. Success is determined by the provider response.
        """
        if self.family != HYPERHIVE_JSONRPC:
            raise ValueError("inferred HyperHive execution requires a HyperHive session")

        normalized = tuple(str(item) for item in markers)
        marker_map = _marker_map(normalized)
        if marker_map.get("method") != "play":
            raise ValueError("inferred HyperHive route must resolve to method=play")
        features = _marker_values(normalized, "purchased_feature")
        if len(features) > 1:
            raise ValueError(
                "inferred HyperHive route has ambiguous purchased_feature values"
            )

        values = dict(overrides or {})
        req: dict[str, Any] = {
            "bet": values.get("bet", self.default_bet),
        }
        for key in (
            "purchased_feature",
            "purchased_feature_level",
            "action",
            "bet_type",
        ):
            raw = marker_map.get(key)
            if raw is not None and raw != "":
                req[key] = _marker_scalar(raw)

        params: dict[str, Any] = {
            "token": self.token,
            "req": req,
        }
        if self.state_lock is not None:
            params["state_lock"] = self.state_lock

        payload = {
            "id": _fresh_rpc_id(self.rpc_id_sample),
            "jsonrpc": "2.0",
            "method": "play",
            "params": params,
        }
        result = self.http.post_json(
            self.endpoint_url,
            payload,
            timeout_s=self.timeout_s,
            headers=self.headers,
            allow_http_error=True,
        )
        response = _json_object(result.text, "play")
        success = (
            200 <= result.status < 400
            and response.get("error") in (None, {}, [])
        )
        if success:
            current = response.get("result")
            if isinstance(current, dict) and "state_lock" in current:
                self.state_lock = current.get("state_lock")

        return {
            "status": result.status,
            "success": success,
            "endpoint": sanitize_session_url(self.endpoint_url),
            "request": redact(payload),
            "response": redact(response),
        }

    def _open_classic(self, html: str) -> None:
        bootstrap = extract_bootstrap_options(html)
        self.endpoint_url = bootstrap.api
        parsed = urlsplit(bootstrap.api)
        self.headers = {
            "Origin": f"{parsed.scheme}://{parsed.netloc}",
            "Referer": self.launch_url,
            bootstrap.csrf_header_name: bootstrap.csrf_header_value,
        }
        init_payload = {
            "command": "init",
            "extra_data": {"round_series_id": self.round_series_id},
        }
        result = self.http.post_json(
            bootstrap.api,
            init_payload,
            timeout_s=self.timeout_s,
            headers=self.headers,
        )
        self.current_init = _json_object(result.text, "init")

        if not is_legacy_init(self.current_init) and not isinstance(
            self.current_init.get("options"),
            dict,
        ):
            retry_payload = {
                "command": "init",
                "extra_data": {
                    "round_series_id": self.round_series_id,
                    "api_version": 2,
                },
            }
            retry = self.http.post_json(
                bootstrap.api,
                retry_payload,
                timeout_s=self.timeout_s,
                headers=self.headers,
                allow_http_error=True,
            )
            retry_data = _json_object(retry.text, "init")
            if isinstance(retry_data.get("options"), dict):
                result = retry
                init_payload = retry_payload
                self.current_init = retry_data
        if is_legacy_init(self.current_init):
            self.family = LEGACY_LINES
            wager, _count, _options = legacy_spin_options(self.current_init)
            self.default_bet = wager
        else:
            self.family = API_V2
            self.default_bet = resolve_base_bet(self.current_init)
        self.api_templates = extract_api_v2_templates(self.evidence)

    def _open_hyperhive(self, outer_html: str) -> None:
        if not _is_hyperhive_url(self.launch_url):
            raise ValueError("HAR says HyperHive but current runtime is not HyperHive.")

        options = extract_window_options(outer_html)
        token = str(options.get("play_token") or "").strip()
        if not token:
            raise ValueError("current HyperHive bootstrap has no play_token")
        self.token = token

        origin = _origin(self.launch_url)
        inner_url = origin + "/?token=" + quote(token, safe="")
        self.http.get(
            inner_url,
            timeout_s=self.timeout_s,
            headers={"Referer": self.launch_url},
        )
        observed_init = _observed_hyperhive_init(self.evidence)
        if observed_init is None:
            raise ValueError(
                "HAR has no successful HyperHive init request; capture one before direct replay."
            )
        observed_url, init_payload = observed_init
        self.endpoint_url = origin + urlsplit(observed_url).path
        params = init_payload.get("params")
        if not isinstance(params, dict):
            raise TypeError("observed HyperHive init has no params object")
        params = deepcopy(params)
        params["token"] = token
        init_payload["params"] = params
        init_payload["id"] = _fresh_rpc_id(init_payload.get("id"))
        self.rpc_id_sample = init_payload.get("id")

        self.headers = {
            "Origin": origin,
            "Referer": inner_url,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        result = self.http.post_json(
            self.endpoint_url,
            init_payload,
            timeout_s=self.timeout_s,
            headers=self.headers,
            allow_http_error=True,
        )
        payload = _json_object(result.text, "init")
        _require_rpc_success(payload, "init", result.status)
        current = payload.get("result")
        if not isinstance(current, dict):
            raise TypeError("HyperHive init result is not an object")
        self.current_init = current
        self.state_lock = current.get("state_lock")
        self.default_bet = resolve_hyperhive_bet(current)
        self.hyper_templates = extract_hyperhive_templates(self.evidence)

    def _can_execute(self, markers: tuple[str, ...]) -> tuple[bool, str]:
        marker_map = _marker_map(markers)
        if self.family == HYPERHIVE_JSONRPC:
            if marker_map.get("method") != "play":
                return False, "only observed HyperHive play actions are executable"
            template = choose_hyperhive_template(
                self.hyper_templates,
                action=marker_map.get("action", ""),
                purchased_feature=marker_map.get("purchased_feature", ""),
            )
            return (
                (True, "")
                if template is not None
                else (False, "no unique successful HyperHive wire template for this action")
            )

        command = marker_map.get("command")
        if not command:
            return False, "action has no observed command marker"
        if self.family == LEGACY_LINES and command == "spin":
            return True, ""
        template = choose_api_v2_template(
            self.api_templates,
            command=command,
            purchased_feature=marker_map.get("purchased_feature", ""),
            purchased_feature_level=marker_map.get("purchased_feature_level", ""),
        )
        return (
            (True, "")
            if template is not None
            else (False, "no unique successful API-v2 wire template for this action")
        )

    def _execute_classic(
        self,
        markers: tuple[str, ...],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        marker_map = _marker_map(markers)
        command = marker_map["command"]

        if self.family == LEGACY_LINES and command == "spin":
            _wager, _count, options = legacy_spin_options(self.current_init)
            if "bet" in overrides:
                requested = overrides["bet"]
                bets = options.get("bets")
                if isinstance(bets, dict):
                    options["bets"] = {key: requested for key in bets}
            payload = {
                "command": "spin",
                "options": options,
                "extra_data": {
                    "client_seed": secrets.randbelow(100000),
                    "round_series_id": self.round_series_id,
                },
            }
        else:
            template = choose_api_v2_template(
                self.api_templates,
                command=command,
                purchased_feature=marker_map.get("purchased_feature", ""),
                purchased_feature_level=marker_map.get("purchased_feature_level", ""),
            )
            if template is None:
                raise ValueError("no unique observed API-v2 template")
            payload = apply_api_v2_template(
                template,
                fresh_options=self._fresh_api_options(template, overrides),
                fresh_extra_data=self._fresh_api_extra(template, overrides),
            )

        result = self.http.post_json(
            self.endpoint_url,
            payload,
            timeout_s=self.timeout_s,
            headers=self.headers,
            allow_http_error=True,
        )
        response = _json_value(result.text)
        return {
            "status": result.status,
            "request": redact(payload),
            "response": redact(response),
        }

    def _fresh_api_options(
        self,
        template: ApiV2Template,
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        dynamic = dict(overrides.get("dynamic") or {})
        for key in template.option_dynamic_shapes:
            lowered = key.casefold()
            if key in dynamic:
                out[key] = dynamic[key]
            elif lowered in {"bet", "stake", "amount", "wager"}:
                out[key] = overrides.get("bet", self.default_bet)
            else:
                raise ValueError(f"direct replay needs override for dynamic options.{key}")
        return out

    def _fresh_api_extra(
        self,
        template: ApiV2Template,
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        dynamic = dict(overrides.get("dynamic") or {})
        for key in template.extra_dynamic_shapes:
            lowered = key.casefold()
            if key in dynamic:
                out[key] = dynamic[key]
            elif lowered == "round_series_id":
                out[key] = self.round_series_id
            elif lowered == "client_seed":
                out[key] = secrets.randbelow(100000)
            elif lowered == "timestamp":
                out[key] = int(time.time() * 1000)
            else:
                raise ValueError(f"direct replay needs override for dynamic extra_data.{key}")
        return out

    def _execute_hyperhive(
        self,
        markers: tuple[str, ...],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        marker_map = _marker_map(markers)
        template = choose_hyperhive_template(
            self.hyper_templates,
            action=marker_map.get("action", ""),
            purchased_feature=marker_map.get("purchased_feature", ""),
        )
        if template is None:
            raise ValueError("no unique observed HyperHive template")

        bet = overrides.get("bet", _observed_template_bet(self.evidence, template.evidence_id))
        if bet is None:
            bet = self.default_bet

        params: dict[str, Any] = {
            "token": self.token,
            "req": {"bet": bet},
        }
        if template.state_lock_present:
            params["state_lock"] = "" if self.state_lock is None else self.state_lock

        rebuilt = apply_hyperhive_template(params, template)
        payload = {
            "id": _fresh_rpc_id(self.rpc_id_sample),
            "jsonrpc": "2.0",
            "method": "play",
            "params": rebuilt,
        }
        result = self.http.post_json(
            self.endpoint_url,
            payload,
            timeout_s=self.timeout_s,
            headers=self.headers,
            allow_http_error=True,
        )
        response = _json_object(result.text, "play")
        if 200 <= result.status < 400 and response.get("error") in (None, {}, []):
            current = response.get("result")
            if isinstance(current, dict) and "state_lock" in current:
                self.state_lock = current.get("state_lock")

        return {
            "status": result.status,
            "request": redact(payload),
            "response": redact(response),
        }


def serve_bgaming_demo_port(
    *,
    har_path: str | Path,
    url: str,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("BGaming demo port only binds to loopback.")

    session = BGamingDemoDirectSession(
        har_path=har_path,
        url=url,
        timeout_s=timeout_s,
    )
    session.open()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/state":
                self._json(200, session.state())
                return
            if self.path == "/actions":
                self._json(200, {"actions": [item.to_dict() for item in session.actions()]})
                return
            if self.path == "/routes":
                self._json(200, {"routes": session.routes()})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            action_prefix = "/actions/"
            route_prefix = "/routes/"
            if self.path.startswith(action_prefix):
                target = self.path[len(action_prefix) :].strip("/")
                executor = session.execute
            elif self.path.startswith(route_prefix):
                target = self.path[len(route_prefix) :].strip("/")
                executor = session.execute_route
            else:
                self._json(404, {"error": "not found"})
                return
            try:
                body = self._read_json()
                result = executor(target, overrides=body)
            except KeyError as exc:
                self._json(404, {"error": str(exc)})
                return
            except (TypeError, ValueError, RuntimeError) as exc:
                self._json(409, {"error": str(exc)})
                return
            self._json(200, result)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise TypeError("request body must be a JSON object")
            return value

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, int(port)), Handler)
    print(
        json.dumps(
            {
                "listening": f"http://{host}:{int(port)}",
                "state": session.state(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _observed_hyperhive_init(evidence) -> tuple[str, dict[str, Any]] | None:
    for exchange in evidence.http:
        body = exchange.request_body
        if (
            exchange.response_status is not None
            and 200 <= exchange.response_status < 400
            and isinstance(body, dict)
            and body.get("jsonrpc") == "2.0"
            and body.get("method") == "init"
        ):
            return exchange.url, deepcopy(body)
    return None


def _observed_template_bet(evidence, evidence_id: str) -> Any:
    for exchange in evidence.http:
        if exchange.evidence_id != evidence_id:
            continue
        body = exchange.request_body
        if not isinstance(body, dict):
            return None
        params = body.get("params")
        req = params.get("req") if isinstance(params, dict) else None
        return req.get("bet") if isinstance(req, dict) else None
    return None


def _marker_values(markers: tuple[str, ...], key: str) -> list[str]:
    prefix = f"{key}="
    return list(
        dict.fromkeys(
            marker[len(prefix) :]
            for marker in markers
            if marker.startswith(prefix) and marker[len(prefix) :]
        )
    )


def _marker_map(markers: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for marker in markers:
        if "=" not in marker:
            continue
        key, value = marker.split("=", 1)
        out[key] = value
    return out


def _marker_scalar(value: str) -> Any:
    text = str(value).strip()
    if not text:
        return text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(parsed, (str, int, float, bool)) or parsed is None:
        return parsed
    return text


def _fresh_rpc_id(sample: Any) -> int | str:
    if isinstance(sample, int) and not isinstance(sample, bool):
        return sample + 1 if sample else 0
    return str(uuid.uuid4())


def _json_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _json_object(text: str, phase: str) -> dict[str, Any]:
    value = _json_value(text)
    if not isinstance(value, dict):
        raise TypeError(f"{phase} response is not a JSON object")
    return value


def _require_rpc_success(payload: dict[str, Any], phase: str, status: int) -> None:
    if not 200 <= status < 400:
        raise RuntimeError(f"HyperHive {phase} HTTP {status}")
    if payload.get("error") not in (None, {}, []):
        raise RuntimeError(f"HyperHive {phase} RPC error: {payload.get('error')!r}")


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _require_demo_intent(url: str) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    if host == "bgaming.com" or host.endswith(".bgaming.com"):
        return
    if "/fun" not in path:
        raise ValueError("direct request port is restricted to BGaming demo/FUN URLs")


def _require_demo_runtime(url: str) -> None:
    host = (urlsplit(url).hostname or "").casefold()
    if host == "demo.bgaming-network.com" or ".demo.bgaming-network.com" in host:
        return
    raise ValueError("resolved runtime is not a BGaming demo host")
