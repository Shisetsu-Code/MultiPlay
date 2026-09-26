from multiplay.browser.explorer import _safe_url, event_is_stateful, event_signature


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
