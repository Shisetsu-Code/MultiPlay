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
