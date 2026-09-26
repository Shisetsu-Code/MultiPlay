from multiplay.providers.bgaming import (
    ACCEPTED,
    PROVEN,
    SEMANTIC_REJECTION,
    UNRESOLVED,
    probe_contiguous_index_domain,
    prove_contiguous_index_domain,
)


def test_proves_contiguous_domain_only_after_repeated_boundary_rejection():
    probes = [
        {"index": 0, "outcome": ACCEPTED},
        {"index": 1, "outcome": ACCEPTED},
        {"index": 2, "outcome": ACCEPTED},
        {"index": 3, "outcome": SEMANTIC_REJECTION},
        {"index": 3, "outcome": SEMANTIC_REJECTION},
    ]
    proof = prove_contiguous_index_domain(probes)
    assert proof["state"] == PROVEN
    assert proof["required_indices"] == [0, 1, 2]
    assert proof["boundary_index"] == 3


def test_one_boundary_rejection_is_not_enough():
    proof = prove_contiguous_index_domain(
        [
            {"index": 0, "outcome": ACCEPTED},
            {"index": 1, "outcome": SEMANTIC_REJECTION},
        ]
    )
    assert proof["state"] == UNRESOLVED


def test_probe_stops_at_first_stable_rejection():
    calls = []

    def probe(index):
        calls.append(index)
        if index < 4:
            return {"outcome": ACCEPTED}
        return {"outcome": SEMANTIC_REJECTION}

    proof = probe_contiguous_index_domain(probe, max_index=10)
    assert proof["state"] == PROVEN
    assert proof["required_indices"] == [0, 1, 2, 3]
    assert calls == [0, 1, 2, 3, 4, 4]
