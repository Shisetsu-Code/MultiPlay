from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .analyzer import MultiProtocolAnalyzer
from .endpoints import ProviderKnowledgeStore
from .evidence import load_har
from .models import AnalysisStatus
from .providers import apply_provider_validation, default_provider_registry


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

    finalize = sub.add_parser("finalize-provider", help="Close a provider analysis snapshot")
    finalize.add_argument("provider")
    finalize.add_argument("--knowledge-root", default="knowledge/providers")
    finalize.add_argument("--unresolved", action="append", default=[])
    finalize.add_argument("--notes", default="")

    args = parser.parse_args()
    if args.command == "analyze-har":
        return _analyze(args)
    if args.command == "finalize-provider":
        return _finalize(args)
    raise AssertionError(args.command)


def _analyze(args: argparse.Namespace) -> int:
    evidence = load_har(args.har)
    analysis = MultiProtocolAnalyzer().analyze(evidence, provider=args.provider)

    provider_decision = None
    provider_blockers: list[str] = []
    if args.provider:
        registry = default_provider_registry()
        try:
            adapter = registry.get(args.provider)
        except KeyError:
            provider_blockers = [
                f"No provider adapter is registered for {args.provider!r}."
            ]
            analysis.status = AnalysisStatus.PARTIAL_REQUIRES_REVIEW
            analysis.reasons = list(dict.fromkeys([*analysis.reasons, *provider_blockers]))
        else:
            provider_decision = adapter.recognize(evidence, analysis.contracts)
            provider_blockers = apply_provider_validation(analysis, evidence, adapter)

    payload = {
        "status": analysis.status.value,
        "provider": analysis.provider,
        "provider_decision": asdict(provider_decision) if provider_decision is not None else None,
        "provider_blockers": provider_blockers,
        "detections": [asdict(item) for item in analysis.detections],
        "contracts": [
            {
                "family": contract.family,
                "unresolved": contract.unresolved,
                "metadata": contract.metadata,
                "transitions": [
                    {
                        **asdict(transition),
                        "transport": transition.transport.value,
                    }
                    for transition in contract.transitions
                ],
            }
            for contract in analysis.contracts
        ],
        "reasons": analysis.reasons,
    }

    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.provider:
        source_ref = args.source_ref or str(args.har)
        ProviderKnowledgeStore(args.knowledge_root).record_analysis(
            provider=args.provider,
            analysis=analysis,
            evidence=evidence,
            source_ref=source_ref,
            environment=args.environment,
        )
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
