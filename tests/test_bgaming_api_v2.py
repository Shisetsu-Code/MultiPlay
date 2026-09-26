import pytest

from multiplay.models import EvidenceBundle, HttpExchange
from multiplay.providers.bgaming.api_v2 import (
    apply_api_v2_template,
    choose_api_v2_template,
    extract_api_v2_templates,
)


def _exchange(body, response=None):
    return HttpExchange(
        evidence_id="wire",
        method="POST",
        url="https://demo.bgaming-network.com/api/Foo/12345/session",
        request_body=body,
        response_status=200,
        response_body=response or {"flow": {"state": "closed", "available_actions": ["spin"]}},
    )


def test_purchase_template_keeps_selectors_and_refreshes_dynamic_fields():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                {
                    "command": "spin",
                    "options": {
                        "bet": 100,
                        "purchased_feature": "freespin_buy",
                        "purchased_feature_level": "1",
                    },
                    "extra_data": {
                        "round_series_id": 123,
                        "client": "web",
                    },
                }
            )
        ]
    )
    template = choose_api_v2_template(
        extract_api_v2_templates(evidence),
        command="spin",
        purchased_feature="freespin_buy",
        purchased_feature_level="1",
    )

    assert template is not None
    replay = apply_api_v2_template(
        template,
        fresh_options={"bet": 200},
        fresh_extra_data={"round_series_id": 456},
    )
    assert replay == {
        "command": "spin",
        "options": {
            "bet": 200,
            "purchased_feature": "freespin_buy",
            "purchased_feature_level": "1",
        },
        "extra_data": {
            "round_series_id": 456,
            "client": "web",
        },
    }


def test_legacy_line_shape_must_match_observed_mapping():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                {
                    "command": "spin",
                    "options": {
                        "lines": {"0": 1, "1": 1, "2": 1},
                    },
                    "extra_data": {"round_series_id": 123},
                }
            )
        ]
    )
    template = extract_api_v2_templates(evidence)[0]

    with pytest.raises(ValueError, match="shape differs"):
        apply_api_v2_template(
            template,
            fresh_options={"lines": {"0": 2, "1": 2}},
            fresh_extra_data={"round_series_id": 456},
        )


def test_sensitive_extra_value_is_never_persisted_in_template():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                {
                    "command": "spin",
                    "options": {"bet": "1.00"},
                    "extra_data": {
                        "round_series_id": 123,
                        "session_token": "captured-secret",
                    },
                }
            )
        ]
    )
    template = extract_api_v2_templates(evidence)[0]

    assert "captured-secret" not in repr(template)
    replay = apply_api_v2_template(
        template,
        fresh_options={"bet": "2.00"},
        fresh_extra_data={
            "round_series_id": 456,
            "session_token": "fresh-secret",
        },
    )
    assert replay["extra_data"]["session_token"] == "fresh-secret"


def test_unobserved_dynamic_field_is_rejected():
    evidence = EvidenceBundle(
        http=[
            _exchange(
                {
                    "command": "spin",
                    "options": {"bet": 100},
                    "extra_data": {"round_series_id": 123},
                }
            )
        ]
    )
    template = extract_api_v2_templates(evidence)[0]

    with pytest.raises(ValueError, match="not demonstrated as dynamic"):
        apply_api_v2_template(
            template,
            fresh_options={"bet": 200, "invented": True},
            fresh_extra_data={"round_series_id": 456},
        )
