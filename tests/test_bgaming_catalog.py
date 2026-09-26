import multiplay.providers.bgaming.catalog as catalog_module
from multiplay.providers.bgaming.catalog import crawl_catalog, parse_catalog_html


def test_catalog_parser_keeps_stable_demo():
    html = """
    <div data-catalog-card data-image="/img/foo.webp">
      <a href="https://bgaming.com/games/foo-game">Details</a>
      <a href="https://demo.bgaming-network.com/play/FooGame/demo">Play Demo</a>
      <img alt="Foo Game" src="/img/foo-fallback.webp">
      <span class="game-type-text">Slots</span>
      <span class="paragraph-98">High</span>
      <div>RTP 96.50%</div>
    </div>
    """

    records = parse_catalog_html(html)
    assert len(records) == 1
    item = records[0]
    assert item.slug == "foo-game"
    assert item.name == "Foo Game"
    assert item.identifier == "FooGame"
    assert item.game_type == "Slots"
    assert item.volatility == "High"
    assert item.rtp == 96.5
    assert item.availability == "DEMO"
    assert item.execution_url == item.demo_url


def test_catalog_parser_never_persists_ephemeral_demo_token():
    html = """
    <div data-catalog-card>
      <a href="https://bgaming.com/games/bar-game">Details</a>
      <a href="https://demo.bgaming-network.com/hyperhive?launch_token=SECRET">
        Play Demo
      </a>
      <img alt="Bar Game">
      <span class="game-type-text">Slots</span>
    </div>
    """

    item = parse_catalog_html(html)[0]
    assert item.availability == "EPHEMERAL_DEMO"
    assert item.demo_url == ""
    assert item.execution_url == "https://bgaming.com/games/bar-game"
    assert "SECRET" not in repr(item)


def test_catalog_parser_marks_coming_soon_without_demo():
    html = """
    <div data-catalog-card>
      <a href="/games/future-game">Details</a>
      <img alt="Future Game">
      <span class="game-type-text">Slots</span>
      <div>Coming Soon</div>
    </div>
    """

    item = parse_catalog_html(html)[0]
    assert item.availability == "COMING_SOON"
    assert item.execution_url.endswith("/games/future-game")


def test_full_catalog_paginates_rest_and_stays_authoritative(monkeypatch):
    first_html = """
    <div data-catalog-card>
      <a href="/games/first">Details</a>
      <a href="https://demo.bgaming-network.com/play/First/FUN">Play Demo</a>
      <img alt="First">
      <span class="game-type-text">Slots</span>
    </div>
    """
    page_two = """
    <div data-catalog-card>
      <a href="/games/second">Details</a>
      <a href="https://demo.bgaming-network.com/play/Second/FUN">Play Demo</a>
      <img alt="Second">
      <span class="game-type-text">Slots</span>
    </div>
    """

    monkeypatch.setattr(
        catalog_module,
        "fetch_catalog_html",
        lambda *_args, **_kwargs: first_html,
    )
    monkeypatch.setattr(
        catalog_module,
        "_fetch_catalog_page",
        lambda *_args, **_kwargs: {
            "page": 2,
            "total": 2,
            "hasMore": False,
            "html": page_two,
        },
    )

    result = crawl_catalog()
    assert result.authoritative is True
    assert result.pages == 2
    assert [item.slug for item in result.records] == ["first", "second"]


def test_catalog_marks_total_change_non_authoritative(monkeypatch):
    first_html = """
    <div data-catalog-card>
      <a href="/games/first">Details</a>
      <img alt="First">
      <span class="game-type-text">Slots</span>
    </div>
    """
    payloads = {
        2: {"page": 2, "total": 3, "hasMore": True, "html": first_html},
        3: {"page": 3, "total": 4, "hasMore": False, "html": first_html},
    }

    monkeypatch.setattr(
        catalog_module,
        "fetch_catalog_html",
        lambda *_args, **_kwargs: first_html,
    )
    monkeypatch.setattr(
        catalog_module,
        "_fetch_catalog_page",
        lambda *_args, page, **_kwargs: payloads[page],
    )

    result = crawl_catalog()
    assert result.authoritative is False
    assert any("total changed" in item for item in result.diagnostics)
