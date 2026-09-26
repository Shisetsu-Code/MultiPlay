from multiplay.browser.explorer import (
    ClickCandidate,
    _candidate_key,
    _next_candidate,
    _safe_url,
    event_is_stateful,
    event_signature,
)


def test_http_post_is_stateful():
    event = {
        "kind": "http_request",
        "method": "POST",
        "url": "https://example.test/api",
    }
    assert event_is_stateful(event)
    assert event_signature(event) == "POST example.test/api"


def test_http_get_is_not_stateful():
    assert not event_is_stateful(
        {
            "kind": "http_request",
            "method": "GET",
            "url": "https://example.test/assets/game.js",
        }
    )


def test_websocket_send_is_stateful():
    event = {
        "kind": "websocket_sent",
        "url": "wss://example.test/game",
    }
    assert event_is_stateful(event)
    assert event_signature(event) == "WS example.test/game"


def test_safe_url_redacts_credentials_but_keeps_nonsecret_query():
    safe = _safe_url(
        "https://example.test/play?launch_token=secret&lang=en&session_id=abc"
    )
    assert "secret" not in safe
    assert "abc" not in safe
    assert "lang=en" in safe



def test_visual_candidate_identity_changes_with_patch_fingerprint():
    first = ClickCandidate("visual", 100, 200, 10, fingerprint="aaa")
    second = ClickCandidate("visual", 100, 200, 10, fingerprint="bbb")
    assert _candidate_key(first) != _candidate_key(second)


def test_persistent_dom_candidate_is_not_retried():
    candidate = ClickCandidate("dom", 100, 200, 1000, label="button volume")
    seen = {_candidate_key(candidate)}
    assert _next_candidate([candidate], seen) is None
