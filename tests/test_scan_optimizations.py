# -*- coding: utf-8 -*-
"""扫描性能优化相关测试：
1. 在线数据整体不可用时在线因子给中性分（不稀释综合分）
2. _calc_indicators_from_rows 复用外部指标与全量计算一致
"""
import random

from strategies import _calc_indicators_from_rows, check_strategy, get_strategies
from strategy_schema import (
    build_factor_defs, default_rules, score_factor_set, total_score,
)
from tests.conftest import closes_to_rows, trading_dates


def _ctx_factory():
    return {
        "close": 12.0, "pct": 3.0, "ma5": 12.1, "ma10": 11.8, "ma20": 11.2,
        "ma60": 10.0, "rsi6": 60.0, "macd": 0.3, "kd_strong": True,
        "kd_weak": False, "vol_ratio": 1.8, "amplitude": 2.0, "is_break": True,
        "bull_arrange": True, "profit_ratio": 0.9, "main_net": 0.0,
        "dde_net": 0.0, "pe": 0.0, "pb": 0.0, "rev_yoy": 0.0,
        "profit_yoy": 0.0, "market_score": 1.0, "board_score": 1.0,
        "limit_up_5": 1,
    }


def test_score_factor_online_empty_neutral():
    """在线数据整体不可用(online_empty=True)时，在线/实时因子给中性 5 分，
    避免 0 分稀释综合分导致小资金 min_score 门槛下漏选。"""
    defs = build_factor_defs(None)
    rmap = default_rules()
    ctx = _ctx_factory()

    s_avail = score_factor_set(defs, ctx, rmap)
    s_empty = score_factor_set(defs, ctx, rmap, online_empty=True)

    for k in ("main_flow", "dde", "growth", "valuation",
              "order_book", "position"):
        assert s_empty[k] == 5.0, f"{k} 应给中性 5 分"
        assert s_avail[k] == 0.0, f"{k} 在线可用时应按规则打分(此处全 0)"

    t_empty = total_score(defs, s_empty)
    t_avail = total_score(defs, s_avail)
    assert t_empty > t_avail, "短路后总分不应低于在线空 0 分场景（避免稀释）"

    # 本地因子不受 online_empty 影响
    assert s_empty["trend"] == s_avail["trend"]
    assert s_empty["momentum"] == s_avail["momentum"]


def test_score_factor_online_empty_backtest_unchanged():
    """回测 active_sources={SRC_LOCAL} 语义不受 online_empty 影响。"""
    from strategy_schema import SRC_LOCAL
    defs = build_factor_defs(None)
    rmap = default_rules()
    ctx = _ctx_factory()
    s_local = score_factor_set(defs, ctx, rmap, active_sources={SRC_LOCAL},
                               online_empty=True)
    for k in ("main_flow", "dde", "growth", "valuation"):
        assert s_local[k] == 0.0, "回测中在线因子恒 0（不受中性分影响）"


def _make_rows(n=80, seed=1):
    rng = random.Random(seed)
    rows = []
    c = 10.0
    for _ in range(n):
        c = max(1, c + rng.uniform(-0.6, 0.6))
        rows.append({"close": round(c, 2), "high": round(c + 0.3, 2),
                     "low": round(c - 0.3, 2), "volume": rng.randint(1000, 9000)})
    return rows


def test_calc_indicators_reuse_matches_full():
    """外部指标复用分支与全量计算产出的键、值完全一致。"""
    rows = _make_rows()
    full = _calc_indicators_from_rows(rows)
    ext = {k: full[k] for k in ("ma5", "ma10", "ma20", "ma60", "macd", "rsi6")}
    fast = _calc_indicators_from_rows(rows, ext)

    assert set(fast) == set(full), (sorted(fast), sorted(full))
    for k in full:
        assert fast[k] == full[k], (k, fast[k], full[k])


def test_calc_indicators_fallback_on_missing_keys():
    """外部指标缺少关键键时应回退全量计算。"""
    rows = _make_rows()
    full = _calc_indicators_from_rows(rows)
    fast = _calc_indicators_from_rows(rows, {"ma5": 1, "ma10": 2})
    assert fast["macd"] == full["macd"]
    assert fast["rsi6"] == full["rsi6"]


def test_get_strategies_includes_factor_default():
    """策略注册表应包含综合因子策略（扫描下拉框来源）。"""
    strategies = get_strategies()
    fd = next((s for s in strategies if s["key"] == "factor_default"), None)
    assert fd is not None, "扫描下拉框缺少综合因子策略"
    assert fd["min_score"] == 48.0
    assert callable(fd["check"])
    # 所有 v9 策略仍保留
    assert "v9Screen" in [s["key"] for s in strategies]


def test_check_strategy_factor_default_hits():
    """综合因子策略无硬条件：check_strategy 恒命中（门槛由综合分判定）。"""
    assert check_strategy("factor_default", _make_rows(), {}) is True


# ---------- v9Limit5 连板启动前一日 ----------
def _limit5_closes(limit_days, n=100, base=10.0, daily=0.004):
    """构造收盘价序列：limit_days 为涨停日索引集合，其余日按 daily 温和变化。"""
    closes = []
    px = base
    for j in range(n):
        if j in limit_days:
            px *= 1.10
        else:
            px *= (1 + daily)
        closes.append(round(px, 2))
    return closes


def test_get_strategies_includes_v9_limit5():
    """注册表应包含 v9Limit5 连板启动前一日策略（扫描下拉框来源）。"""
    strategies = get_strategies()
    s = next((s for s in strategies if s["key"] == "v9Limit5"), None)
    assert s is not None, "扫描下拉框缺少 v9Limit5 策略"
    assert callable(s["check"])
    assert "连板" in s["name"]


def test_check_strategy_v9_limit5_hits_prelaunch_day():
    """连板启动前一日形态应命中：近20日涨停>=2/近60日>=8/距上次涨停<=45日，
    收盘站上MA20（偏离0~25%）且收盘>MA60（偏离>-5%），当日未涨停、非ST。"""
    limit_days = {52, 56, 60, 64, 68, 72, 76, 82, 87, 92}
    rows = closes_to_rows(_limit5_closes(limit_days), code="600000", name="测试")
    calc = _calc_indicators_from_rows(rows)
    dev20 = (calc["close"] / calc["ma20"] - 1) * 100
    dev60 = (calc["close"] / calc["ma60"] - 1) * 100
    assert 0 < dev20 <= 25, f"close_ma20 应为 0~25%，实际 {dev20:.2f}%"
    assert dev60 > -5, f"close_ma60 应 >-5%，实际 {dev60:.2f}%"
    assert rows[-1]["pct_chg"] < 8, "启动前一日当日应未涨停"
    assert check_strategy("v9Limit5", rows, {}) is True


def test_check_strategy_v9_limit5_misses():
    """无涨停基因/当日已涨停/破位/ST 均不应命中。"""
    # 无涨停基因：纯温和上涨
    rows = closes_to_rows(_limit5_closes(set()), code="600000", name="测试")
    assert check_strategy("v9Limit5", rows, {}) is False
    # 涨停基因足够但当日已涨停（启动当日而非前一日）
    limit_days = {52, 56, 60, 64, 68, 72, 76, 82, 87, 92, 99}
    rows = closes_to_rows(_limit5_closes(limit_days), code="600000", name="测试")
    assert rows[-1]["pct_chg"] >= 8, "测试数据应有当日涨停"
    assert check_strategy("v9Limit5", rows, {}) is False
    # 涨停基因足够但收盘破位（MA20下方）
    rows = closes_to_rows(_limit5_closes({10, 20, 30, 40, 50, 60, 70},
                                         daily=-0.008), code="600000", name="测试")
    calc = _calc_indicators_from_rows(rows)
    assert (calc["close"] / calc["ma20"] - 1) * 100 < 0, "测试数据应破位"
    assert check_strategy("v9Limit5", rows, {}) is False
    # ST 不命中
    rows = closes_to_rows(_limit5_closes({52, 56, 60, 64, 68, 72, 76, 82, 87, 92}),
                          code="600000", name="ST测试")
    assert check_strategy("v9Limit5", rows, {}) is False
