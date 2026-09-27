from multiplay.models import EvidenceBundle, ScriptEvidence
from multiplay.providers.bgaming.switchable import (
    extract_switchable_variants,
    route_child_index,
    switchable_child_url,
)


def test_extract_switchable_variants_from_runtime_array():
    evidence = EvidenceBundle(
        scripts=[
            ScriptEvidence(
                evidence_id="s",
                source="https://demo.bgaming-network.com/bundle.js",
                text=(
                    'const ks=["AllLuckyClover5","AllLuckyClover20",'
                    '"AllLuckyClover40","AllLuckyClover100"];'
                ),
            )
        ]
    )
    assert extract_switchable_variants(evidence, "AllLuckyClover") == [
        "AllLuckyClover5",
        "AllLuckyClover20",
        "AllLuckyClover40",
        "AllLuckyClover100",
    ]


def test_switchable_child_url_uses_parent_host():
    assert switchable_child_url(
        "https://demo.bgaming-network.com/play/AllLuckyClover/FUN?server=demo",
        "AllLuckyClover100",
    ) == "https://demo.bgaming-network.com/play/AllLuckyClover100/FUN"


def test_route_child_index_reads_handler_argument():
    assert route_child_index(
        {"handler": "classes.LuckyCloverScene.setCurrentGame" + chr(96) + "3"}
    ) == 3
    assert route_child_index(
        {"handler": "currentScene.setCurrentGame" + chr(96) + "2,1"}
    ) == 2
