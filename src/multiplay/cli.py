from __future__ import annotations

import argparse
import json
from pathlib import Path

from .batch import analyze_har_directory
from .endpoints import ProviderKnowledgeStore
from .evidence import load_har
from .pipeline import analyze_evidence


def main() -> int:
    parser = argparse.ArgumentParser(prog="multiplay")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze-har", help="Infer protocol contracts from a HAR")
    analyze.add_argument("har")
    analyze.add_argument("--provider")
    analyze.add_argument("--source-ref")
    analyze.add_argument("--environment", choices=("demo", "live"), default="demo")
    analyze.add_argument("--knowledge-root", default="knowledge/providers")
    analyze.add_argument("--output")

    har_map = sub.add_parser(
        "har-map",
        help="List observed endpoints and UI/action candidates extracted from HAR code",
    )
    har_map.add_argument("har")
    har_map.add_argument("--action")
    har_map.add_argument("--output")
    har_map.add_argument("--json", action="store_true")

    har_actions = sub.add_parser(
        "har-actions",
        help="Resolve declared controls through handlers to protocol actions",
    )
    har_actions.add_argument("har")
    har_actions.add_argument("--route")
    har_actions.add_argument("--all", action="store_true")
    har_actions.add_argument("--output")
    har_actions.add_argument("--json", action="store_true")

    direct_port = sub.add_parser(
        "bgaming-port",
        help="Serve observed BGaming demo actions over a loopback HTTP port",
    )
    direct_port.add_argument("har")
    direct_port.add_argument("url")
    direct_port.add_argument("--host", default="127.0.0.1")
    direct_port.add_argument("--port", type=int, default=8765)
    direct_port.add_argument("--timeout", type=float, default=30.0)

    browser_explore = sub.add_parser(
        "browser-explore",
        help="Discover visible controls with Playwright and correlate clicks to network effects",
    )
    browser_explore.add_argument("url")
    browser_explore.add_argument("--output-dir", required=True)
    browser_explore.add_argument("--max-clicks", type=int, default=24)
    browser_explore.add_argument("--settle-ms", type=int, default=3500)
    browser_explore.add_argument("--headed", action="store_true")

    browser_discover = sub.add_parser(
        "bgaming-browser-discover",
        help="Select a BGaming runtime family and discover its actions through Playwright",
    )
    browser_discover.add_argument("--catalog", required=True)
    browser_discover.add_argument("--family", required=True)
    browser_discover.add_argument("--output-dir", required=True)
    browser_discover.add_argument("--max-probes", type=int, default=80)
    browser_discover.add_argument("--probe-delay", type=float, default=1.0)
    browser_discover.add_argument("--timeout", type=float, default=30.0)
    browser_discover.add_argument("--max-clicks", type=int, default=28)
    browser_discover.add_argument("--settle-ms", type=int, default=4000)
    browser_discover.add_argument("--headed", action="store_true")
    browser_discover.add_argument("--keep-har", action="store_true")
    browser_discover.add_argument("--knowledge-root", default="knowledge/providers")
    browser_discover.add_argument(
        "--family-map",
        default="knowledge/providers/bgaming/family-map.json",
    )
    browser_discover.add_argument("--output")

    hyperhive = sub.add_parser(
        "bgaming-hyperhive-demo",
        help="Execute one HyperHive demo init/play using the current client wire",
    )
    hyperhive.add_argument("url")
    hyperhive.add_argument("--timeout", type=float, default=30.0)
    hyperhive.add_argument("--knowledge-root", default="knowledge/providers")
    hyperhive.add_argument("--output")

    demo_spin = sub.add_parser(
        "bgaming-demo-spin",
        help="Execute one BGaming demo base spin and record the observed wire",
    )
    demo_spin.add_argument("url")
    demo_spin.add_argument("--timeout", type=float, default=30.0)
    demo_spin.add_argument("--knowledge-root", default="knowledge/providers")
    demo_spin.add_argument("--output")

    probe = sub.add_parser(
        "bgaming-probe",
        help="Resolve a BGaming demo and run a non-wagering bootstrap/init probe",
    )
    probe.add_argument("url")
    probe.add_argument("--timeout", type=float, default=30.0)
    probe.add_argument("--knowledge-root", default="knowledge/providers")
    probe.add_argument("--output")

    capture = sub.add_parser(
        "capture-har",
        help="Open a headed browser and record an interactive HAR session",
    )
    capture.add_argument("url")
    capture.add_argument("--output", required=True)
    capture.add_argument("--screenshot")

    analyze_dir = sub.add_parser("analyze-dir", help="Analyze every HAR in a directory")
    analyze_dir.add_argument("directory")
    analyze_dir.add_argument("--provider")
    analyze_dir.add_argument("--environment", choices=("demo", "live"), default="demo")
    analyze_dir.add_argument("--knowledge-root", default="knowledge/providers")
    analyze_dir.add_argument("--no-recursive", action="store_true")
    analyze_dir.add_argument("--output")

    sweep = sub.add_parser(
        "bgaming-sweep",
        help="Probe a BGaming catalog without wagering and summarize runtime families",
    )
    sweep.add_argument("--catalog", required=True)
    sweep.add_argument("--limit", type=int, default=0)
    sweep.add_argument("--delay", type=float, default=0.25)
    sweep.add_argument("--timeout", type=float, default=30.0)
    sweep.add_argument("--knowledge-root", default="knowledge/providers")
    sweep.add_argument("--output")

    catalog = sub.add_parser("bgaming-catalog", help="Fetch/parse the BGaming slots catalog")
    catalog.add_argument("--url", default="https://bgaming.com/game-type/slots")
    catalog.add_argument("--html")
    catalog.add_argument("--output")
    catalog.add_argument("--max-pages", type=int, default=100)

    finalize = sub.add_parser("finalize-provider", help="Close a provider analysis snapshot")
    finalize.add_argument("provider")
    finalize.add_argument("--knowledge-root", default="knowledge/providers")
    finalize.add_argument("--unresolved", action="append", default=[])
    finalize.add_argument("--notes", default="")

    args = parser.parse_args()
    if args.command == "analyze-har":
        return _analyze(args)
    if args.command == "har-map":
        return _har_map(args)
    if args.command == "har-actions":
        return _har_actions(args)
    if args.command == "bgaming-port":
        return _bgaming_port(args)
    if args.command == "browser-explore":
        return _browser_explore(args)
    if args.command == "bgaming-browser-discover":
        return _bgaming_browser_discover(args)
    if args.command == "bgaming-hyperhive-demo":
        return _bgaming_hyperhive_demo(args)
    if args.command == "bgaming-demo-spin":
        return _bgaming_demo_spin(args)
    if args.command == "bgaming-probe":
        return _bgaming_probe(args)
    if args.command == "capture-har":
        return _capture_har(args)
    if args.command == "analyze-dir":
        return _analyze_dir(args)
    if args.command == "bgaming-sweep":
        return _bgaming_sweep(args)
    if args.command == "bgaming-catalog":
        return _bgaming_catalog(args)
    if args.command == "finalize-provider":
        return _finalize(args)
    raise AssertionError(args.command)


def _analyze(args: argparse.Namespace) -> int:
    evidence = load_har(args.har)
    result = analyze_evidence(evidence, provider=args.provider)
    source_ref = args.source_ref or str(args.har)

    rendered = json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.provider:
        records = (
            result.provider_adapter.endpoint_records(
                evidence,
                result.analysis,
                source_ref=source_ref,
                environment=args.environment,
            )
            if result.provider_adapter is not None
            else None
        )
        ProviderKnowledgeStore(args.knowledge_root).record_analysis(
            provider=args.provider,
            analysis=result.analysis,
            evidence=evidence,
            source_ref=source_ref,
            environment=args.environment,
            records=records,
        )
    return 0


def _har_map(args: argparse.Namespace) -> int:
    from .har_map import build_har_map, render_har_map

    report = build_har_map(args.har)
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if args.json and not args.action:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_har_map(report, action_id=args.action), end="")
    return 0


def _har_actions(args: argparse.Namespace) -> int:
    from .action_graph import build_action_graph, render_action_graph

    graph = build_action_graph(args.har, include_all=args.all)
    if args.output:
        Path(args.output).write_text(
            json.dumps(graph, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if args.json and not args.route:
        print(json.dumps(graph, indent=2, ensure_ascii=False))
    else:
        print(render_action_graph(graph, route_id=args.route), end="")
    return 0


def _bgaming_port(args: argparse.Namespace) -> int:
    from .providers.bgaming.direct_port import serve_bgaming_demo_port

    serve_bgaming_demo_port(
        har_path=args.har,
        url=args.url,
        host=args.host,
        port=args.port,
        timeout_s=args.timeout,
    )
    return 0


def _browser_explore(args: argparse.Namespace) -> int:
    from .browser import explore_browser

    result = explore_browser(
        url=args.url,
        output_dir=args.output_dir,
        max_clicks=args.max_clicks,
        settle_ms=args.settle_ms,
        headless=not args.headed,
    )
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _bgaming_browser_discover(args: argparse.Namespace) -> int:
    from .providers.bgaming.browser_discovery import discover_family_with_browser

    result = discover_family_with_browser(
        catalog_path=args.catalog,
        family=args.family,
        output_dir=args.output_dir,
        max_probes=args.max_probes,
        probe_delay_s=args.probe_delay,
        timeout_s=args.timeout,
        max_clicks=args.max_clicks,
        settle_ms=args.settle_ms,
        headless=not args.headed,
        knowledge_root=args.knowledge_root,
        keep_har=args.keep_har,
        family_map_path=args.family_map,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _bgaming_hyperhive_demo(args: argparse.Namespace) -> int:
    from .providers.bgaming.hyperhive_demo import run_demo_hyperhive

    demo = run_demo_hyperhive(args.url, timeout_s=args.timeout)
    result = analyze_evidence(demo.evidence, provider="bgaming")
    source_ref = "demo-hyperhive:" + demo.metadata.launch_url
    records = (
        result.provider_adapter.endpoint_records(
            demo.evidence,
            result.analysis,
            source_ref=source_ref,
            environment="demo",
        )
        if result.provider_adapter is not None
        else None
    )
    ProviderKnowledgeStore(args.knowledge_root).record_analysis(
        provider="bgaming",
        analysis=result.analysis,
        evidence=demo.evidence,
        source_ref=source_ref,
        environment="demo",
        records=records,
    )
    payload = {
        "demo": demo.metadata.to_dict(),
        "analysis": result.to_dict(),
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _bgaming_demo_spin(args: argparse.Namespace) -> int:
    from .providers.bgaming.demo_spin import run_demo_base_spin

    demo = run_demo_base_spin(args.url, timeout_s=args.timeout)
    result = analyze_evidence(demo.evidence, provider="bgaming")
    source_ref = "demo-spin:bgaming:" + demo.metadata.identifier
    records = (
        result.provider_adapter.endpoint_records(
            demo.evidence,
            result.analysis,
            source_ref=source_ref,
            environment="demo",
        )
        if result.provider_adapter is not None
        else None
    )
    ProviderKnowledgeStore(args.knowledge_root).record_analysis(
        provider="bgaming",
        analysis=result.analysis,
        evidence=demo.evidence,
        source_ref=source_ref,
        environment="demo",
        records=records,
    )
    payload = {
        "demo": demo.metadata.to_dict(),
        "analysis": result.to_dict(),
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _bgaming_probe(args: argparse.Namespace) -> int:
    from .providers.bgaming.probe import probe_bgaming_demo

    probe = probe_bgaming_demo(args.url, timeout_s=args.timeout)
    result = analyze_evidence(probe.evidence, provider="bgaming")
    source_ref = "probe:" + probe.metadata.to_dict()["launch_url"]
    records = (
        result.provider_adapter.endpoint_records(
            probe.evidence,
            result.analysis,
            source_ref=source_ref,
            environment="demo",
        )
        if result.provider_adapter is not None
        else None
    )
    ProviderKnowledgeStore(args.knowledge_root).record_analysis(
        provider="bgaming",
        analysis=result.analysis,
        evidence=probe.evidence,
        source_ref=source_ref,
        environment="demo",
        records=records,
    )
    payload = {
        "probe": probe.metadata.to_dict(),
        "analysis": result.to_dict(),
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _capture_har(args: argparse.Namespace) -> int:
    from .browser import capture_interactive_har

    capture_interactive_har(
        url=args.url,
        har_path=args.output,
        screenshot_path=args.screenshot,
    )
    print(args.output)
    return 0


def _analyze_dir(args: argparse.Namespace) -> int:
    report = analyze_har_directory(
        args.directory,
        provider=args.provider,
        environment=args.environment,
        knowledge_root=args.knowledge_root,
        recursive=not args.no_recursive,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0

def _bgaming_sweep(args: argparse.Namespace) -> int:
    from .providers.bgaming.sweep import sweep_catalog_file

    report = sweep_catalog_file(
        args.catalog,
        limit=args.limit,
        delay_s=args.delay,
        timeout_s=args.timeout,
        knowledge_root=args.knowledge_root,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _bgaming_catalog(args: argparse.Namespace) -> int:
    from .providers.bgaming.catalog import (
        catalog_crawl_json,
        catalog_json,
        crawl_catalog,
        parse_catalog_html,
    )

    if args.html:
        html = Path(args.html).read_text(encoding="utf-8")
        rendered = catalog_json(parse_catalog_html(html, base_url=args.url))
    else:
        rendered = catalog_crawl_json(
            crawl_catalog(
                catalog_url=args.url,
                max_pages=args.max_pages,
            )
        )
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _finalize(args: argparse.Namespace) -> int:
    path = ProviderKnowledgeStore(args.knowledge_root).finalize_provider(
        provider=args.provider,
        unresolved=args.unresolved,
        notes=args.notes,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
