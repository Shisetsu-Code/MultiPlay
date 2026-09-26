import json

import multiplay.providers.bgaming.probe as probe_module
from multiplay.pipeline import analyze_evidence
from multiplay.providers.bgaming.probe import probe_bgaming_demo


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def get(self, url, *, timeout_s):
        del url, timeout_s
        return self.responses.pop(0)

    def post_json(self, url, payload, *, timeout_s, headers):
        self.posts.append((url, payload, headers))
        del timeout_s
        return self.responses.pop(0)


def test_classic_probe_executes_init_and_classifies_api_v2(monkeypatch):
    launch_html = """
    <script>
      window.__OPTIONS__ = {
        "api":"https://demo.bgaming-network.com/api/Foo/12345/session-secret",
        "identifier":"Foo",
        "csrfTokenHeaderName":"X-CSRF",
        "csrfTokenHeaderValue":"csrf-secret"
      };
    </script>
    """
    session = FakeSession(
        [
            probe_module._HttpResult(
                200,
                "https://demo.bgaming-network.com/play/Foo/FUN",
                launch_html,
            ),
            probe_module._HttpResult(
                200,
                "https://demo.bgaming-network.com/api/Foo/12345/session-secret",
                json.dumps(
                    {
                        "options": {"bets": [100]},
                        "flow": {
                            "state": "closed",
                            "available_actions": ["spin"],
                        },
                        "balance": 1000,
                    }
                ),
            ),
        ]
    )
    monkeypatch.setattr(probe_module, "_HttpSession", lambda: session)

    result = probe_bgaming_demo(
        "https://demo.bgaming-network.com/play/Foo/FUN"
    )
    analysis = analyze_evidence(result.evidence, provider="bgaming")

    assert result.metadata.init_executed is True
    assert result.metadata.identifier == "Foo"
    assert "session-secret" not in repr(result.evidence)
    assert any(
        reason == "runtime:api-v2"
        for reason in analysis.provider_decision.reasons
    )


def test_public_detail_resolves_demo_candidate_in_memory(monkeypatch):
    public = probe_module._HttpResult(
        200,
        "https://bgaming.com/games/foo",
        '<a href="https://demo.bgaming-network.com/play/Foo/FUN">Play Demo</a>',
    )
    launch = probe_module._HttpResult(
        200,
        "https://demo.bgaming-network.com/play/Foo/FUN",
        """
        <script>
          window.__OPTIONS__ = {
            "api":"https://demo.bgaming-network.com/api/Foo/12345/session",
            "identifier":"Foo",
            "csrfTokenHeaderName":"X-CSRF",
            "csrfTokenHeaderValue":"secret"
          };
        </script>
        """,
    )
    init = probe_module._HttpResult(
        200,
        "https://demo.bgaming-network.com/api/Foo/12345/session",
        json.dumps(
            {
                "options": {"bets": [100]},
                "flow": {"state": "closed", "available_actions": ["spin"]},
            }
        ),
    )
    session = FakeSession([public, launch, init])
    monkeypatch.setattr(probe_module, "_HttpSession", lambda: session)

    result = probe_bgaming_demo("https://bgaming.com/games/foo")
    assert result.metadata.launch_url.endswith("/play/Foo/FUN")
    assert session.posts


def test_hyperhive_probe_classifies_without_guessing_init_wire(monkeypatch):
    session = FakeSession(
        [
            probe_module._HttpResult(
                200,
                "https://demo.bgaming-network.com/hyperhive?launch_token=secret",
                "<html></html>",
            )
        ]
    )
    monkeypatch.setattr(probe_module, "_HttpSession", lambda: session)

    result = probe_bgaming_demo(
        "https://demo.bgaming-network.com/hyperhive?launch_token=secret"
    )
    analysis = analyze_evidence(result.evidence, provider="bgaming")

    assert result.metadata.init_executed is False
    assert "launch_token" not in result.metadata.to_dict()["launch_url"]
    assert any(
        reason == "runtime:hyperhive-jsonrpc"
        for reason in analysis.provider_decision.reasons
    )
