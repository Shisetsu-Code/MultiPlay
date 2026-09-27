from multiplay.providers.bgaming.hyperhive_demo import resolve_hyperhive_bet
from multiplay.providers.bgaming.hyperhive_wire_profile import (
    analyze_current_wire,
    build_profile_request,
)


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


def test_flat_hyperhive_profile_reconstructs_client_play_shape():
    profile = analyze_current_wire(
        'class G{constructor(){this.buyBonusModeMultiplier=60}};'
        'let n=x?"freebet":"default",r=1;'
        '"buy_bonus"==e&&(r=this.globalState.buyBonusModeMultiplier);'
        'this.network.invoke("play",{token:this.network.token,req:{'
        'bet:i,bet_type:n,fe_exponent:this.globalState.feBetExponent,'
        'purchased_feature:e,balance:this.globalState.balance,'
        'buyBonusModeMultiplier:r}})'
    )

    assert profile.bet_type == "default"
    assert profile.req_purchased_feature is True
    assert profile.req_balance is True
    assert profile.req_fe_exponent is True
    assert profile.req_buy_bonus_multiplier is True
    assert profile.base_buy_bonus_multiplier == 1
    assert profile.buy_bonus_multiplier == 60
    assert profile.state_lock_present is False

    init_result = {
        "balance": 100000,
        "currency_attributes": {
            "subunits": 100,
            "exponent": 2,
        },
        "config": {
            "default_bet": 30,
            "bet_limits": [10, 20, 30, 50],
        },
    }

    assert build_profile_request(
        profile,
        init_result,
        bet=30,
    ) == {
        "bet": 30,
        "bet_type": "default",
        "fe_exponent": 2,
        "balance": 100000,
        "buyBonusModeMultiplier": 1,
    }

    assert build_profile_request(
        profile,
        init_result,
        bet=30,
        purchased_feature="buy_bonus",
    )["buyBonusModeMultiplier"] == 60


def test_optional_purchase_feature_is_omitted_from_normal_spin():
    profile = analyze_current_wire(
        'x={method:"play",params:{token:t,req:{bet:a,bet_type:"bet"},state_lock:""}};'
        'if(buy)x.params.req.purchased_feature="buy_bonus";'
    )
    req = build_profile_request(
        profile,
        {
            "config": {"default_bet": 200, "bet_limits": [20, 200]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=200,
    )
    assert "purchased_feature" not in req


def test_intercom_hyperhive_profile_builds_normal_action_request():
    profile = analyze_current_wire(
        'j=void 0;'
        'U={bet:g,integrationId:C,bet_type:R?"freebet":"bet",'
        'purchased_feature:j,modelRev:0,minExponent:y.state.ui.minExponent};'
        'c.action({state_lock:i.stateLock,req:U});'
    )
    assert profile.bet_type == "bet"
    assert profile.state_lock_present is True
    assert profile.req_model_rev == 0
    assert profile.req_min_exponent is True
    assert profile.req_integration_id is True
    assert profile.req_purchased_feature is True
    assert profile.req_purchased_feature_omit_empty is True

    req = build_profile_request(
        profile,
        {
            "config": {"default_bet": 200, "bet_limits": [20, 40, 200]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=200,
    )
    assert req == {
        "bet": 200,
        "bet_type": "bet",
        "modelRev": 0,
        "minExponent": 2,
    }

def test_custom_request_uses_last_game_specific_normal_spin_map():
    profile = analyze_current_wire(
        'initRequestMap(){return this.RequestMap={'
        '[A.Regular]:{ActionType:T.SPIN,AdditionalData:{request:T.SPIN,'
        'rel:R.NEW_SPIN,params:{selectedWinLines:[],perLine:!0,isFeatureBuy:!1}}}}}'
        'setRequestConfig(){this._requestMap[A.Regular]={ActionType:T.SPIN,'
        'AdditionalData:{request:T.SPIN,rel:R.NEW_SPIN,'
        'params:{selectedWinLines:[0,1,2,3],perLine:!0}}}}'
        'formattedRequest.params.action=t;'
        'formattedRequest.params.exponent=2;'
        'formattedRequest.params.stake=a;'
        'x.req.custom_req=formattedRequest.params;'
        'x={method:"play",params:{token:q,req:{bet:a,bet_type:"bet"},state_lock:""}}'
    )
    assert profile.custom_literals == {
        "selectedWinLines": [0, 1, 2, 3],
        "perLine": True,
    }

    req = build_profile_request(
        profile,
        {
            "config": {"default_bet": 200, "bet_limits": [20, 200]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=200,
    )
    assert req["custom_req"] == {
        "selectedWinLines": [0, 1, 2, 3],
        "perLine": True,
        "action": "spin",
        "exponent": 2,
        "stake": 200,
    }


def test_custom_request_recovers_game_specific_buy_flags():
    profile = analyze_current_wire(
        'this._requestMap[A.Regular]={ActionType:T.SPIN,AdditionalData:{'
        'request:T.SPIN,rel:R.NEW_SPIN,'
        'params:{isNormalBuy:!1,isSuperBuy:!1}}};'
        'formattedRequest.params.action=t;'
        'x.req.custom_req=formattedRequest.params;'
        'x={method:"play",params:{token:q,req:{bet:a,bet_type:"bet"},state_lock:""}}'
    )
    assert profile.custom_literals == {
        "isNormalBuy": False,
        "isSuperBuy": False,
    }

def test_play_profile_ignores_init_action_and_omits_conditional_purchase():
    profile = analyze_current_wire(
        'init:async t=>post("/api",{jsonrpc:"2.0",method:"init",'
        'params:{token:t,req:{action:"INIT"}}});'
        'play:async(i,e,t,n)=>post("/api",{jsonrpc:"2.0",method:"play",'
        'params:{token:q,req:{bet:i,bet_type:"bet",'
        '...n?{instant_bonus_game:n}:{},'
        '...n?{purchased_feature:"buy_bonus"}:{},'
        '...e?{ante_bet:!0}:{},...t?{wild_bet:!0}:{}}}})'
    )
    assert profile.req_action is False
    assert profile.req_purchased_feature is True
    assert profile.req_purchased_feature_always is False
    assert profile.req_purchased_feature_omit_empty is True

    normal = build_profile_request(
        profile,
        {
            "config": {"default_bet": 100, "bet_limits": [20, 100]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=100,
    )
    assert normal == {"bet": 100, "bet_type": "bet"}

    bought = build_profile_request(
        profile,
        {
            "config": {"default_bet": 100, "bet_limits": [20, 100]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=100,
        purchased_feature="buy_bonus",
    )
    assert bought["purchased_feature"] == "buy_bonus"

def test_profile_prefers_normal_spin_when_bundle_has_multiple_play_requests():
    profile = analyze_current_wire(
        'bonus={jsonrpc:"2.0",method:"play",params:{req:{'
        'bet:b,bet_type:"betting",action:"bonus"},state_lock:s,token:t}};'
        'normal={jsonrpc:"2.0",method:"play",params:{req:{'
        'bet:b,bet_type:"betting",action:"spin"},state_lock:s,token:t}};'
        'purchase={jsonrpc:"2.0",method:"play",params:{req:{'
        'bet:b,bet_type:"betting",purchased_feature:"buy_bonus"},'
        'state_lock:s,token:t}};'
    )
    assert profile.req_action is True
    assert profile.req_purchased_feature is False
    assert profile.bet_type == "betting"
    assert profile.state_lock_present is True

    req = build_profile_request(
        profile,
        {
            "config": {"default_bet": 100, "bet_limits": [20, 100]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=100,
    )
    req["action"] = "spin"
    assert req == {
        "bet": 100,
        "bet_type": "betting",
        "action": "spin",
    }

def test_variable_action_is_detected_in_play_request():
    profile = analyze_current_wire(
        'function request(mode){let action="";'
        'mode==="BASE"?action="spin":mode==="FREEGAME"&&(action="freespin");'
        'return fetch("/api",{body:JSON.stringify({jsonrpc:"2.0",method:"play",'
        'params:{req:{bet:100,action:action,bet_type:"bet"},token:t}})})}'
    )
    assert profile.req_action is True

    req = build_profile_request(
        profile,
        {
            "config": {"default_bet": 100, "bet_limits": [20, 100]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=100,
    )
    assert req == {"bet": 100, "bet_type": "bet"}


def test_variable_purchased_feature_is_optional_for_normal_spin():
    profile = analyze_current_wire(
        'async play(bet,purchased,bonus,freebet){'
        'const req={bet:bet,purchased_feature:purchased,bonus_buy:bonus};'
        'freebet&&(req.bet_type="freebet");'
        'return fetch("/api",{body:JSON.stringify({jsonrpc:"2.0",method:"play",'
        'params:{token:t,req:req}})})}'
    )
    assert profile.req_purchased_feature is True
    assert profile.req_purchased_feature_always is False

    req = build_profile_request(
        profile,
        {
            "config": {"default_bet": 100, "bet_limits": [20, 100]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=100,
    )
    assert "purchased_feature" not in req

def test_custom_request_recovers_generated_line_indexes():
    profile = analyze_current_wire(
        'setRequestConfig(){this._requestMap[F.Regular]={'
        'ActionType:T.SPIN,AdditionalData:{request:T.SPIN,rel:R.NEW_SPIN,'
        'params:{selectedWinLines:Array.from({length:20},((t,e)=>e)),'
        'perLine:!0,isNormalBuy:!1,isSuperBuy:!1}}}}'
        'formattedRequest.params.action=t;'
        'formattedRequest.params.exponent=2;'
        'x.req.custom_req=formattedRequest.params;'
        'x={method:"play",params:{token:q,req:{bet:a,bet_type:"bet"},state_lock:""}}'
    )
    assert profile.custom_literals == {
        "selectedWinLines": list(range(20)),
        "perLine": True,
        "isNormalBuy": False,
        "isSuperBuy": False,
    }

    req = build_profile_request(
        profile,
        {
            "config": {"default_bet": 200, "bet_limits": [20, 200]},
            "currency_attributes": {"subunits": 100, "exponent": 2},
        },
        bet=200,
    )
    assert req["custom_req"]["selectedWinLines"] == list(range(20))
    assert req["custom_req"]["isNormalBuy"] is False
    assert req["custom_req"]["isSuperBuy"] is False

