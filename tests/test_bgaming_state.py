from multiplay.models import EvidenceBundle, HttpExchange
from multiplay.providers.bgaming.state import (
    build_feature_session,
    state_from_payload,
)


def _exchange(eid, command, options, response):
    return HttpExchange(
        evidence_id=eid,
        method="POST",
        url="https://demo.bgaming-network.com/api/Foo/12345/session",
        request_body={
            "command": command,
            "options": options,
            "extra_data": {"round_series_id": 1},
        },
        response_status=200,
        response_body=response,
    )


def test_closed_is_terminal_only_when_spin_returns():
    not_terminal = state_from_payload(
        {"flow": {"state": "closed", "available_actions": ["collect"]}}
    )
    terminal = state_from_payload(
        {"flow": {"state": "closed", "available_actions": ["spin"]}}
    )

    assert not_terminal is not None and not_terminal.terminal is None
    assert terminal is not None and terminal.terminal is True


def test_builds_feature_round_sequence():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "spin",
                "spin",
                {"bet": 100},
                {
                    "flow": {
                        "state": "freespins",
                        "available_actions": ["freespin"],
                    }
                },
            ),
            _exchange(
                "fs1",
                "freespin",
                {},
                {
                    "flow": {
                        "state": "freespins",
                        "available_actions": ["freespin"],
                    }
                },
            ),
            _exchange(
                "fs2",
                "freespin",
                {},
                {
                    "flow": {
                        "state": "closed",
                        "available_actions": ["spin"],
                    }
                },
            ),
        ]
    )

    session = build_feature_session(evidence)
    assert session is not None
    assert len(session.rounds) == 2
    assert session.terminal is True


def test_choice_domain_comes_from_previous_server_state():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                "spin",
                "spin",
                {"bet": 100},
                {
                    "flow": {
                        "state": "select_bonus",
                        "available_actions": ["select_bonus"],
                    },
                    "game": {
                        "freespin_params": {
                            "variants": [{"name": "a"}, {"name": "b"}]
                        }
                    },
                },
            ),
            _exchange(
                "choice",
                "select_bonus",
                {"name": "b"},
                {
                    "flow": {
                        "state": "freespins",
                        "available_actions": ["freespin"],
                    }
                },
            ),
            _exchange(
                "fs",
                "freespin",
                {},
                {
                    "flow": {
                        "state": "closed",
                        "available_actions": ["spin"],
                    }
                },
            ),
        ]
    )

    session = build_feature_session(evidence)
    assert session is not None
    choice = session.rounds[-1].choices[0]
    assert choice.options == ("a", "b")
    assert choice.selected == "b"
    assert choice.wire_field == "name"
