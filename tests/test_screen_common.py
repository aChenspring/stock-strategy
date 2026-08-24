"""共享筛选判定（screen_common）测试：扫描与回测共用同一套过滤代码。"""
from screen_common import (DEFAULT_SCAN_FILTERS, passes_market_filters,
                           passes_indicator_filters, passes_online_filters,
                           evaluate_buy)


def _row(pct=2.0, close=10.0, name="测试股份", amount=5e8, turnover=3.0):
    return {"pct_chg": pct, "close": close, "name": name,
            "amount": amount, "turnover": turnover}


# ---------- 默认筛选条件 ----------
def test_default_filters_all_boards_non_st():
    """默认口径 = 全市场 + 非ST（回测全市场调优，扫描必须对齐）。"""
    assert DEFAULT_SCAN_FILTERS["non_st"] is True
    assert DEFAULT_SCAN_FILTERS["boards"]["main"] is True
    assert DEFAULT_SCAN_FILTERS["boards"]["gem"] is True
    assert DEFAULT_SCAN_FILTERS["boards"]["star"] is True
    assert DEFAULT_SCAN_FILTERS["boards"]["bse"] is True


# ---------- 行情过滤 ----------
def test_market_filter_empty_passes():
    assert passes_market_filters("600000", [_row()], {}) is True


def test_market_filter_non_st():
    assert passes_market_filters("600000", [_row(name="*ST海投")],
                                 {"non_st": True}) is False
    assert passes_market_filters("600000", [_row(name="海投")],
                                 {"non_st": True}) is True


def test_market_filter_boards():
    f = {"boards": {"main": True}}
    assert passes_market_filters("600000", [_row()], f) is True
    assert passes_market_filters("300001", [_row()], f) is False
    assert passes_market_filters("300001", [_row()],
                                 {"boards": {"gem": True}}) is True


def test_market_filter_price_amount():
    f = {"price_min": 8, "price_max": 20, "amount_min": 2, "amount_max": 10}
    assert passes_market_filters("600000", [_row(close=10, amount=5e8)], f) is True
    assert passes_market_filters("600000", [_row(close=5, amount=5e8)], f) is False
    assert passes_market_filters("600000", [_row(close=10, amount=0.5e8)], f) is False


def test_market_filter_pct_range():
    f = {"pct_chg_min": -3, "pct_chg_max": 5}
    assert passes_market_filters("600000", [_row(pct=2.0)], f) is True
    assert passes_market_filters("600000", [_row(pct=7.0)], f) is False


# ---------- 指标过滤 ----------
def test_indicator_filter_close_above_ma20():
    f = {"close_above_ma20": True}
    assert passes_indicator_filters("600000", {"close": 12.0, "ma20": 10.0},
                                    [_row()], f) is True
    assert passes_indicator_filters("600000", {"close": 9.0, "ma20": 10.0},
                                    [_row()], f) is False


def test_indicator_filter_break_high20_and_macd():
    f = {"break_high20": True, "macd_positive": True}
    ind = {"close": 12.0, "high20": 10.0, "macd": 0.5}
    assert passes_indicator_filters("600000", ind, [_row()], f) is True
    assert passes_indicator_filters("600000", {**ind, "close": 9.0},
                                    [_row()], f) is False
    assert passes_indicator_filters("600000", {**ind, "macd": -0.1},
                                    [_row()], f) is False


def test_indicator_filter_limit_up_recent():
    f = {"limit_up_recent": True}
    rows = [_row(pct=10.0), _row(pct=1.0), _row(pct=1.0), _row(pct=1.0), _row(pct=1.0)]
    assert passes_indicator_filters("600000", {}, rows, f) is True
    assert passes_indicator_filters("600000", {}, [_row(pct=1.0)] * 5, f) is False


# ---------- 在线过滤（数据缺失放行，回测等效） ----------
def test_online_filter_missing_data_passes():
    assert passes_online_filters("600000", [_row()], {}, {},
                                 {"revenue_yoy_positive": True}) is True


def test_online_filter_negative_yoy_blocks():
    online = {"fund": {"revenue_yoy": -5.0}}
    assert passes_online_filters("600000", [_row()], online, {},
                                 {"revenue_yoy_positive": True}) is False


# ---------- evaluate_buy 组合判定 ----------
def test_evaluate_buy_all_pass():
    v = evaluate_buy("600000", [_row(pct=2.0)],
                     {"close": 12.0, "ma20": 10.0}, {},
                     {"close_above_ma20": True, "non_st": True},
                     market_ok=True, max_buy_pct=6.0, strat_hit=True, score=80)
    assert v["ok"] is True and v["limit_ok"] is True
    assert v["market_ok_f"] is True and v["ind_ok"] is True


def test_evaluate_buy_strategy_miss_limit_ok():
    v = evaluate_buy("600000", [_row(pct=2.0)],
                     {"close": 12.0, "ma20": 10.0}, {},
                     {"close_above_ma20": True, "non_st": True},
                     market_ok=True, max_buy_pct=6.0, strat_hit=False, score=50)
    assert v["ok"] is False and v["limit_ok"] is True
    assert v["strat_hit"] is False


def test_evaluate_buy_no_chase_blocks():
    v = evaluate_buy("600000", [_row(pct=8.0)],
                     {"close": 12.0, "ma20": 10.0}, {},
                     {"close_above_ma20": True, "non_st": True},
                     market_ok=True, max_buy_pct=6.0, strat_hit=True)
    assert v["ok"] is False and v["limit_ok"] is False
    assert v["no_chase_ok"] is False
    assert any("不追高" in w for w in v["warnings"])


def test_evaluate_buy_no_chase_boundaries():
    """不追高边界（原 _pass_max_buy_pct 语义迁移）：阈值 None/0/负=不限制；
    pct 缺失放行；恰好等于阈值放行，超过阈值阻塞。"""
    base = {"close": 12.0, "ma20": 10.0}
    for mb in (None, 0, -5):
        v = evaluate_buy("600000", [_row(pct=20.0)], base, {}, {},
                         market_ok=True, max_buy_pct=mb, strat_hit=True)
        assert v["no_chase_ok"] is True and v["ok"] is True, mb
    v = evaluate_buy("600000", [_row(pct=None)], base, {}, {},
                     market_ok=True, max_buy_pct=6.0, strat_hit=True)
    assert v["no_chase_ok"] is True
    v = evaluate_buy("600000", [_row(pct=6.0)], base, {}, {},
                     market_ok=True, max_buy_pct=6.0, strat_hit=True)
    assert v["no_chase_ok"] is True
    v = evaluate_buy("600000", [_row(pct=6.01)], base, {}, {},
                     market_ok=True, max_buy_pct=6.0, strat_hit=True)
    assert v["no_chase_ok"] is False


def test_evaluate_buy_market_filter_blocks():
    v = evaluate_buy("600000", [_row(pct=2.0)],
                     {"close": 12.0, "ma20": 10.0}, {},
                     {"close_above_ma20": True, "non_st": True},
                     market_ok=False, max_buy_pct=6.0, strat_hit=True)
    assert v["ok"] is False and v["limit_ok"] is False
    assert any("大盘过滤" in w for w in v["warnings"])


def test_evaluate_buy_warnings_preserved():
    v = evaluate_buy("600000", [_row(pct=2.0)], {"close": 12.0, "ma20": 10.0},
                     {}, {"non_st": True}, market_ok=True,
                     max_buy_pct=6.0, strat_hit=True,
                     warnings=["已有基础提示"])
    assert v["warnings"][0] == "已有基础提示"
