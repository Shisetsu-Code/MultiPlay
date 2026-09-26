import pytest

from multiplay.models import EvidenceBundle, HttpExchange
from multiplay.providers.bgaming.hyperhive import (
    apply_hyperhive_template,
    choose_hyperhive_template,
    extract_hyperhive_templates,
)


def _play(params):
    return HttpExchange(
        evidence_id="play",
        method="POST",
        url="https://demo.bgaming-network.com/api",
        request_body={
            "id": 0,
            "jsonrpc": "2.0",
            "method": "play",
            "params": params,
        },
        response_status=200,
        response_body={"jsonrpc": "2.0", "id": 0, "result": {"final": True}},
    )


def test_template_preserves_wire_shape_but_not_captured_credentials():
    evidence = EvidenceBundle(
        http=[
            _play(
                {
                    "token": "captured-token",
                    "req": {
                        "bet": "1.00",
                        "bet_type": "bet",
                        "custom_req": {
                            "action": "spin",
                            "exponent": 2,
                            "stake": "1.00",
                        },
                    },
                    "state_lock": "captured-lock",
                    "client_version": 7,
                }
            )
        ]
    )
    template = extract_hyperhive_templates(evidence)[0]

    replay = apply_hyperhive_template(
        {
            "token": "fresh-token",
            "state_lock": "fresh-lock",
            "req": {"bet": "2.00"},
        },
        template,
    )

    assert replay["token"] == "fresh-token"
    assert replay["state_lock"] == "fresh-lock"
    assert replay["client_version"] == 7
    assert replay["req"] == {
        "bet": "2.00",
        "bet_type": "bet",
        "custom_req": {
            "action": "spin",
            "exponent": 2,
            "stake": "2.00",
        },
    }
    assert "captured-token" not in repr(template)
    assert "captured-lock" not in repr(template)


def test_empty_state_lock_presence_is_preserved():
    evidence = EvidenceBundle(
        http=[
            _play(
                {
                    "token": "captured",
                    "req": {"bet": 100, "bet_type": "bet"},
                    "state_lock": "",
                }
            )
        ]
    )
    template = extract_hyperhive_templates(evidence)[0]
    replay = apply_hyperhive_template(
        {"token": "fresh", "req": {"bet": 200}},
        template,
    )

    assert "state_lock" in replay
    assert replay["state_lock"] == ""


def test_bet_scalar_type_mismatch_fails_closed():
    evidence = EvidenceBundle(
        http=[
            _play(
                {
                    "token": "captured",
                    "req": {"bet": "1.00", "bet_type": "bet"},
                    "state_lock": "",
                }
            )
        ]
    )
    template = extract_hyperhive_templates(evidence)[0]

    with pytest.raises(ValueError, match="scalar type"):
        apply_hyperhive_template(
            {"token": "fresh", "req": {"bet": 1}},
            template,
        )


def test_purchase_variant_is_selected_by_observed_discriminators():
    evidence = EvidenceBundle(
        http=[
            _play(
                {
                    "token": "captured",
                    "req": {
                        "bet": 100,
                        "bet_type": "bet",
                        "purchased_feature": "buy_bonus",
                        "custom_req": {
                            "isNormalBuy": True,
                            "isSuperBuy": False,
                            "action": "spin",
                        },
                    },
                    "state_lock": "",
                }
            )
        ]
    )
    templates = extract_hyperhive_templates(evidence)
    selected = choose_hyperhive_template(
        templates,
        action="spin",
        purchased_feature="buy_bonus",
    )

    assert selected is not None
    assert selected.req_static["purchased_feature"] == "buy_bonus"
    assert selected.req_static["custom_req"]["isNormalBuy"] is True
