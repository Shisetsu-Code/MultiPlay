from multiplay.providers.bgaming.hyperhive_demo import resolve_hyperhive_bet
from multiplay.providers.bgaming.hyperhive_wire_profile import analyze_current_wire


def test_current_wire_detects_zero_id_and_state_lock():
    profile = analyze_current_wire(
        'x={id:0,jsonrpc:"2.0",method:"play",params:{token:t,'
        'req:{bet:a,bet_type:"bet"},state_lock:""}}'
    )
    assert profile.rpc_id_zero is True
    assert profile.bet_type == "bet"
    assert profile.state_lock_present is True


def test_current_wire_detects_formatted_custom_request():
    profile = analyze_current_wire(
        'formattedRequest.params.action=t;'
        'formattedRequest.params.exponent=2;'
        'formattedRequest.params.stake=a;'
        'x.req.custom_req=formattedRequest.params;'
        'x.req.bet=a;'
        'x.req.bet_type="betting";'
        'x={method:"play"}'
    )
    assert profile.custom_req is True
    assert profile.custom_action is True
    assert profile.custom_exponent is True
    assert profile.custom_stake is True
    assert profile.bet_type == "betting"


def test_resolve_hyperhive_bet_prefers_default():
    assert resolve_hyperhive_bet(
        {"config": {"default_bet": 100, "bet_limits": [50, 100]}}
    ) == 100


def test_resolve_hyperhive_bet_uses_min_limit():
    assert resolve_hyperhive_bet(
        {"config": {"bet_limits": [500, 100, 200]}}
    ) == 100
