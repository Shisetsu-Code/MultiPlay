from multiplay.providers.bgaming.demo_spin import (
    api_v2_provable_fair_extra_data,
    api_v2_script_spin_option_hints,
    api_v2_spin_retry_options,
    legacy_spin_options,
    resolve_base_bet,
)


def test_resolve_base_bet_prefers_default():
    assert resolve_base_bet(
        {"options": {"default_bet": 20, "available_bets": [10, 20, 50]}}
    ) == 20


def test_resolve_base_bet_falls_back_to_smallest_available():
    assert resolve_base_bet(
        {"options": {"available_bets": [50, 10, 20]}}
    ) == 10


def test_legacy_spin_uses_options_bets_for_every_line():
    wager, count, options = legacy_spin_options(
        {
            "options": {
                "line_bets": [5, 2, 10],
                "lines": [[0], [1], [2]],
            }
        }
    )
    assert wager == 2.0
    assert count == 3
    assert options == {"bets": {"0": 2, "1": 2, "2": 2}}



def test_api_v2_spin_retry_options_uses_init_layout_rows_before_mode():
    retries = api_v2_spin_retry_options(
        {
            "options": {
                "layout": {"reels": 5, "rows": 5},
                "default_bet": 30,
            }
        },
        {"bet": 30},
    )

    assert retries == [
        {"bet": 30, "rows": 5},
        {"bet": 30, "mode": "0"},
        {"bet": 30, "rows": 5, "mode": "0"},
    ]


def test_api_v2_spin_retry_options_does_not_invent_rows():
    retries = api_v2_spin_retry_options(
        {"options": {"default_bet": 20}},
        {"bet": 20},
    )
    assert retries == [{"bet": 20, "mode": "0"}]


def test_api_v2_provable_fair_extra_data_adds_client_seed_only_when_declared():
    assert api_v2_provable_fair_extra_data(
        {"provable_fair": {"verify_url": "https://example.test/verify"}},
        {"round_series_id": 7},
        client_seed=12345,
    ) == {
        "round_series_id": 7,
        "client_seed": 12345,
    }
    assert api_v2_provable_fair_extra_data(
        {},
        {"round_series_id": 7},
        client_seed=12345,
    ) is None


def test_api_v2_script_spin_option_hints_extracts_persistent_literal_levels():
    script = (
        'setSpecialSymbolsLevel(t,e){'
        'this.additionalSpinOptions.gold_symbols_count=""+t;'
        '}'
        'this.setSpecialSymbolsLevel(settings.getItem("special-level",flag?1:3),true);'
    )
    assert api_v2_script_spin_option_hints([script]) == [
        {"gold_symbols_count": "1"},
        {"gold_symbols_count": "3"},
    ]


def test_api_v2_script_spin_option_hints_extracts_literal_mode_switches():
    script = (
        'setCurrentVolatility(t){'
        'this.additionalSpinOptions.volatility='
        '1==this.getCurrentVolatility()?"low":"medium";'
        '}'
    )
    assert api_v2_script_spin_option_hints([script]) == [
        {"volatility": "low"},
        {"volatility": "medium"},
    ]

def test_api_v2_script_spin_option_hints_extracts_prefab_backtick_levels():
    script = (
        'setSpecialSymbolsLevel(t,e){'
        'this.additionalSpinOptions.gold_symbols_count=""+t;'
        '}'
        'onClick:"currentScene.setSpecialSymbolsLevel\x601",'
        'onClick:"currentScene.setSpecialSymbolsLevel\x603",'
        'onClick:"currentScene.setSpecialSymbolsLevel\x605"'
    )
    assert api_v2_script_spin_option_hints([script]) == [
        {"gold_symbols_count": "1"},
        {"gold_symbols_count": "3"},
        {"gold_symbols_count": "5"},
    ]

