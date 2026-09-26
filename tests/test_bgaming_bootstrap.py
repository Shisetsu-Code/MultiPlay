import pytest

from multiplay.providers.bgaming import extract_bootstrap_options, sanitize_bootstrap_options


def test_extracts_window_options_without_bs4():
    html = """
    <html><script>
      window.__OPTIONS__ = {
        "api":"https://demo.bgaming-network.com/api/Game/12345/session-secret",
        "identifier":"Game",
        "csrfTokenHeaderName":"X-CSRF",
        "csrfTokenHeaderValue":"secret",
        "play_token":"launch-secret"
      };
    </script></html>
    """
    options = extract_bootstrap_options(html)
    assert options.identifier == "Game"
    assert options.csrf_header_name == "X-CSRF"

    safe = sanitize_bootstrap_options(options.raw)
    assert safe["csrfTokenHeaderValue"] == "<redacted>"
    assert safe["play_token"] == "<redacted>"
    assert safe["api"].endswith("/api/Game/12345/<session>")


def test_missing_bootstrap_is_rejected():
    with pytest.raises(ValueError):
        extract_bootstrap_options("<html></html>")
