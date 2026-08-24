# -*- coding: utf-8 -*-
"""回测引擎端到端测试：买入/卖出规则、大盘过滤、不追高过滤。"""
import random

import pytest

from backtest import run_backtest
from tests.conftest import closes_to_rows, market_data, trading_dates

BASE_CFG = dict(
    strategy="factor_default",
    start="20260101",
    end="20260430",
    init_cash=1_000_000,
    top_n=5,
    hold_days=10,
    # 费率为 0：单只候选时 shares 按 100 股取整后 cost+fee 可能略超预算，
    # 多只候选场景不受影响，但单股场景需要 0 费率才能精确控制买入
    fee_rate=0.0,
    min_score=-999.0,      # 保证任何候选都能入选，便于控制场景
    stop_loss=-12.0,
    take_profit=20.0,
    rebalance_every=1,
    universe="all",
    max_codes=100,
    pre_days=0,
    market_filter=False,
    max_buy_pct=None,
)


def _patch(monkeypatch, data):
    factory = lambda prefixes, start, end: data
    monkeypatch.setattr("backtest.load_market_rows", factory)
    monkeypatch.setattr("strategy_data.load_market_rows", factory)


def random_market(n_codes=30, n_days=160, seed=7):
    rng = random.Random(seed)
    dates = trading_dates(n_days)
    data = {}
    for i in range(n_codes):
        code = f"{i:06d}"
        px = 10.0 + i
        closes = []
        for j in range(n_days):
            if j and rng.random() < 0.05:
                px = max(2.0, px * 0.97)
            else:
                px = max(2.0, px * (1 + rng.uniform(-0.06, 0.06)))
            closes.append(round(px, 2))
        data[code] = closes_to_rows(closes, code=code, dates=dates)
    return data


# ---------- 扫描/回测判定一致性（judge_at 两端同源） ----------
def test_judge_at_matches_manual_scan_path():
    """judge_at（factor 分支）== 手动复刻的扫描判定路径，逐股逐日一致。

    扫描端 process 与回测买入段共用 judge_at，此测试固化『同一数据同一条件
    命中集合完全相同』，防止两端判定再次分叉。
    """
    from backtest import IndicatorSeries, judge_at
    from screen_common import (DEFAULT_SCAN_FILTERS, evaluate_buy, score_factor_local)
    from strategy_schema import build_factor_defs, build_rules_map

    data = random_market(n_codes=15, n_days=120, seed=11)
    fdefs = build_factor_defs(None)
    rmap = build_rules_map(None)
    min_score, max_buy_pct = 48.0, 6.0
    checked = 0
    for code, rows in data.items():
        s = IndicatorSeries(code, rows)
        for date in s.dates[5:]:
            r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                         min_score, fdefs, rmap, True, "factor_default")
            i = s.index_at(date)
            recent = s.rows[max(0, i - 4):i + 1]
            ind = s.indicator_at(date)
            scored = score_factor_local(fdefs, recent, ind, rmap)
            v = evaluate_buy(code, recent, ind, {}, DEFAULT_SCAN_FILTERS, True,
                             max_buy_pct, strat_hit=scored["total"] >= min_score,
                             score=scored["total"])
            assert (r is not None) == v["ok"], (code, date, r, v)
            if r is not None:
                assert r["scored"]["total"] == scored["total"], (code, date)
            checked += 1
    assert checked > 100


def test_judge_at_v9_matches_manual():
    """judge_at（v9 分支：check_strategy 硬条件 + 综合分排序）== 手动复刻。"""
    from backtest import IndicatorSeries, judge_at
    from screen_common import (DEFAULT_SCAN_FILTERS, evaluate_buy, score_factor_local)
    from strategies import check_strategy
    from strategy_schema import build_factor_defs, build_rules_map

    data = random_market(n_codes=15, n_days=120, seed=13)
    fdefs = build_factor_defs(None)
    rmap = build_rules_map(None)
    checked = 0
    for code, rows in data.items():
        s = IndicatorSeries(code, rows)
        for date in s.dates[5:]:
            r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, None, 0.0,
                         fdefs, rmap, False, "v9B1")
            i = s.index_at(date)
            recent = s.rows[max(0, i - 4):i + 1]
            ind = s.indicator_at(date)
            if not check_strategy("v9B1", s.rows[:i + 1], {}, ind):
                assert r is None, (code, date)
            else:
                scored = score_factor_local(fdefs, recent, ind, rmap)
                v = evaluate_buy(code, recent, ind, {}, DEFAULT_SCAN_FILTERS, True,
                                 None, strat_hit=True, score=scored["total"])
                assert (r is not None) == v["ok"], (code, date)
                if r is not None:
                    assert r["scored"]["total"] == scored["total"], (code, date)
            checked += 1
    assert checked > 100


def test_judge_at_v9_limit5_matches_manual():
    """v9Limit5 连板启动前一日策略：judge_at（v9 分支）== 手动复刻，
    且构造的启动前一日形态在扫描与回测两端一致命中。"""
    from backtest import IndicatorSeries, judge_at
    from screen_common import (DEFAULT_SCAN_FILTERS, evaluate_buy, score_factor_local)
    from strategies import check_strategy
    from strategy_schema import build_factor_defs, build_rules_map

    data = random_market(n_codes=15, n_days=120, seed=23)
    fdefs = build_factor_defs(None)
    rmap = build_rules_map(None)
    checked = hits = 0
    for code, rows in data.items():
        s = IndicatorSeries(code, rows)
        for date in s.dates[5:]:
            r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, None, 0.0,
                         fdefs, rmap, False, "v9Limit5")
            i = s.index_at(date)
            recent = s.rows[max(0, i - 4):i + 1]
            ind = s.indicator_at(date)
            if not check_strategy("v9Limit5", s.rows[:i + 1], {}, ind):
                assert r is None, (code, date)
            else:
                hits += 1
                scored = score_factor_local(fdefs, recent, ind, rmap)
                v = evaluate_buy(code, recent, ind, {}, DEFAULT_SCAN_FILTERS, True,
                                 None, strat_hit=True, score=scored["total"])
                assert (r is not None) == v["ok"], (code, date)
                if r is not None:
                    assert r["scored"]["total"] == scored["total"], (code, date)
            checked += 1
    assert checked > 100
    assert hits == 0, "随机市场不应命中 v9Limit5（无需固定命中）"


def test_judge_at_v9_limit5_hits_on_prelaunch_shape():
    """构造连板启动前一日形态时，judge_at 两端一致命中（扫描/回测同源）。"""
    from backtest import IndicatorSeries, judge_at
    from screen_common import (DEFAULT_SCAN_FILTERS, evaluate_buy, score_factor_local)
    from strategies import check_strategy
    from strategy_schema import build_factor_defs, build_rules_map

    limit_days = {52, 56, 60, 64, 68, 72, 76, 82, 87, 92}
    closes = [10.0]
    for j in range(1, 100):
        if j in limit_days:
            closes.append(round(closes[-1] * 1.10, 2))
        else:
            closes.append(round(closes[-1] * 1.004, 2))
    rows = closes_to_rows(closes, code="600000", name="测试")
    s = IndicatorSeries("600000", rows)
    fdefs = build_factor_defs(None)
    rmap = build_rules_map(None)
    checked = hits = 0
    for date in s.dates[5:]:
        i = s.index_at(date)
        recent = s.rows[max(0, i - 4):i + 1]
        ind = s.indicator_at(date)
        manual = check_strategy("v9Limit5", s.rows[:i + 1], {}, ind)
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, None, 0.0,
                     fdefs, rmap, False, "v9Limit5")
        if not manual:
            assert r is None, (date, "手动不命中但 judge_at 命中")
        else:
            hits += 1
            scored = score_factor_local(fdefs, recent, ind, rmap)
            v = evaluate_buy("600000", recent, ind, {}, DEFAULT_SCAN_FILTERS, True,
                             None, strat_hit=True, score=scored["total"])
            assert (r is not None) == v["ok"], (date, r, v)
        checked += 1
    assert hits > 0, "构造的启动前一日形态应在至少一个交易日命中"
    assert checked > 90


def test_judge_at_return_fail_keeps_verdict_for_scan():
    """judge_at(return_fail=True)：判定不通过也返回 verdict（ok=False），
    扫描端据此展示灰/绿候选；return_fail=False 仍返回 None（回测买入段）。
    """
    from backtest import IndicatorSeries, judge_at
    from screen_common import DEFAULT_SCAN_FILTERS
    from strategy_schema import build_factor_defs, build_rules_map

    data = random_market(n_codes=15, n_days=120, seed=17)
    fdefs = build_factor_defs(None)
    rmap = build_rules_map(None)
    min_score, max_buy_pct = 999.0, 6.0  # min_score 极高 → 策略必不命中
    hit_fail = miss_fail = 0
    for code, rows in data.items():
        s = IndicatorSeries(code, rows)
        for date in s.dates[5:]:
            r0 = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                          min_score, fdefs, rmap, True, "factor_default")
            r1 = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                          min_score, fdefs, rmap, True, "factor_default",
                          return_fail=True)
            if r0 is None:
                miss_fail += 1
                assert r1 is not None, (code, date)
                assert r1["verdict"]["ok"] is False, (code, date)
                assert "ok" in r1["verdict"] and "limit_ok" in r1["verdict"], (code, date)
            else:
                hit_fail += 1
                assert r1["verdict"]["ok"] is True, (code, date)
    # min_score=999 下必然存在不命中样本，且 return_fail 能兜底返回 verdict
    assert miss_fail > 100
    assert hit_fail == 0


def test_judge_at_return_fail_market_ok_false_still_returns():
    """return_fail=True 且 market_ok=False（大盘过滤不通过）：仍返回 verdict，
    limit_ok 为 False（灰色），而不是返回 None 导致扫描结果整体为空。"""
    from backtest import IndicatorSeries, judge_at
    from screen_common import DEFAULT_SCAN_FILTERS
    from strategy_schema import build_factor_defs, build_rules_map

    data = random_market(n_codes=15, n_days=120, seed=19)
    fdefs = build_factor_defs(None)
    rmap = build_rules_map(None)
    min_score, max_buy_pct = 0.0, 6.0  # 策略必命中，但大盘过滤拦截
    checked = 0
    for code, rows in data.items():
        s = IndicatorSeries(code, rows)
        for date in s.dates[5:]:
            r0 = judge_at(s, date, DEFAULT_SCAN_FILTERS, False, max_buy_pct,
                          min_score, fdefs, rmap, True, "factor_default")
            r1 = judge_at(s, date, DEFAULT_SCAN_FILTERS, False, max_buy_pct,
                          min_score, fdefs, rmap, True, "factor_default",
                          return_fail=True)
            assert r0 is None, (code, date)  # 回测段：大盘过滤不通过不买入
            assert r1 is not None, (code, date)  # 扫描段：保留候选展示
            assert r1["verdict"]["ok"] is False, (code, date)
            assert r1["verdict"]["limit_ok"] is False, (code, date)
            assert any("大盘" in w for w in r1["verdict"]["warnings"]), (code, date)
            checked += 1
    assert checked > 100


# ---------- 冒烟 ----------
def test_run_smoke_returns_structure(monkeypatch):
    _patch(monkeypatch, random_market())
    res = run_backtest(BASE_CFG, progress_cb=lambda m, p: None)
    assert set(res) >= {"trades", "metrics", "equity"}
    m = res["metrics"]
    assert m["trade_count"] == len(res["trades"])
    assert m["days"] == len(res["equity"])
    assert m["days"] >= 2
    assert len(res["equity"]) >= 2
    assert all(len(t) == 2 for t in res["equity"])


def test_run_with_market_filter_and_maxbuy_off(monkeypatch):
    # 全开新逻辑跑通
    cfg = dict(BASE_CFG, market_filter=True, max_buy_pct=6.0)
    _patch(monkeypatch, random_market(seed=3))
    res = run_backtest(cfg, progress_cb=lambda m, p: None)
    assert res["metrics"]["trade_count"] == len(res["trades"])


# ---------- 止损 ----------
def test_stop_loss_triggers(monkeypatch):
    closes = [10.0] * 21 + [11.0, 11.5, 11.0, 8.0] + [8.0] * 35  # 共 60 天
    _patch(monkeypatch, market_data({"000001": closes}))
    res = run_backtest(dict(BASE_CFG, min_score=-999.0),
                       progress_cb=lambda m, p: None)
    stops = [t for t in res["trades"] if t["reason"] == "止损"]
    assert stops, [t["reason"] for t in res["trades"]]
    assert stops[0]["pnl"] < 0


# ---------- 止盈 ----------
def test_take_profit_triggers(monkeypatch):
    closes = [10.0] * 21 + [11.0, 12.0, 13.0, 14.0, 15.0] + [15.0] * 34
    _patch(monkeypatch, market_data({"000001": closes}))
    res = run_backtest(dict(BASE_CFG, min_score=-999.0),
                       progress_cb=lambda m, p: None)
    wins = [t for t in res["trades"] if t["reason"] == "止盈"]
    assert wins, [t["reason"] for t in res["trades"]]
    assert wins[0]["pnl"] > 0


# ---------- 持有到期 ----------
def test_hold_expiry(monkeypatch):
    closes = [10.0] * 60
    _patch(monkeypatch, market_data({"000001": closes}))
    res = run_backtest(dict(BASE_CFG, min_score=-999.0),
                       progress_cb=lambda m, p: None)
    reasons = [t["reason"] for t in res["trades"]]
    assert reasons, "横盘也应发生买入"
    assert all(r in ("持有到期", "止损", "止盈", "期末平仓") for r in reasons)
    assert "持有到期" in reasons


# ---------- 大盘过滤（择时） ----------
def test_market_filter_skips_downtrend_buy(monkeypatch):
    # 前 20 天横盘 10，之后跌到 8：指数长期低于 MA20
    closes = [10.0] * 20 + [8.0] * 40
    data = market_data({"000001": closes})
    dates = trading_dates(60)

    _patch(monkeypatch, data)
    on = run_backtest(dict(BASE_CFG, market_filter=True,
                           market_filter_mode="strong", min_score=-999.0),
                      progress_cb=lambda m, p: None)
    off = run_backtest(dict(BASE_CFG, market_filter=False, min_score=-999.0),
                       progress_cb=lambda m, p: None)

    # 过滤开启（strong 模式）：MA20 明显高于指数的下跌段（d20~d35，MA20
    # 从 9.9 降至 8.1）不得买入；MA20 追平指数后恢复买入属正常择时行为
    assert on["trades"], "预热期（MA20 未形成）允许买入"
    assert not any(dates[20] <= t["buy_date"] <= dates[35]
                   for t in on["trades"]), \
        [t["buy_date"] for t in on["trades"]]
    # 过滤关闭：下跌段会买入
    assert any(dates[20] <= t["buy_date"] <= dates[35]
               for t in off["trades"])
    # 过滤开启的总交易数更少
    assert len(on["trades"]) < len(off["trades"])


# ---------- 大盘过滤（oversold 超卖模式） ----------
def test_market_filter_oversold_buys_on_dip(monkeypatch):
    # 单边下跌：指数 RSI 长期超卖（<40），oversold 模式应放行买入
    closes = [10.0] * 20 + [9.8, 9.6, 9.4, 9.2, 9.0,
                            8.8, 8.6, 8.4, 8.2, 8.0] + [7.6, 7.4, 7.2, 7.0] * 10
    _patch(monkeypatch, market_data({"000001": closes}))
    on = run_backtest(dict(BASE_CFG, market_filter=True,
                           market_filter_mode="oversold",
                           market_rsi_threshold=40.0, min_score=-999.0),
                      progress_cb=lambda m, p: None)
    # 超卖窗口（RSI<40）应有买入
    assert on["trades"], "超卖模式应在下跌段放行买入"
    # 同场景 strong 模式：指数在 MA20 下方，下跌段应禁止买入
    strong = run_backtest(dict(BASE_CFG, market_filter=True,
                               market_filter_mode="strong", min_score=-999.0),
                          progress_cb=lambda m, p: None)
    dates = trading_dates(len(closes))
    assert not any(dates[30] <= t["buy_date"] <= dates[45]
                   for t in strong["trades"]), \
        [t["buy_date"] for t in strong["trades"]]


# ---------- 不追高 ----------
def test_max_buy_pct_skips_high_gain_day(monkeypatch):
    data = market_data({"A": [10.0] * 60, "B": [10.0] * 60})
    data["A"][0]["pct_chg"] = 8.0   # 当日 +8% > 阈值 6
    data["B"][0]["pct_chg"] = -2.0
    dates = trading_dates(60)

    _patch(monkeypatch, data)
    res = run_backtest(dict(BASE_CFG, min_score=-999.0, max_buy_pct=6.0,
                            filters={}),   # 关闭筛选过滤链，单独验证不追高
                       progress_cb=lambda m, p: None)

    tb = [t for t in res["trades"] if t["code"] == "B"]
    ta = [t for t in res["trades"] if t["code"] == "A"]
    assert tb, "低涨幅股票应首日买入"
    assert tb[0]["buy_date"] == dates[0]
    assert ta, "高涨幅股票次日应可买入（当日被过滤）"
    assert ta[0]["buy_date"] != dates[0], ta[0]["buy_date"]


def test_no_max_buy_pct_buys_any_day(monkeypatch):
    data = market_data({"A": [10.0] * 60})
    data["A"][0]["pct_chg"] = 8.0
    dates = trading_dates(60)
    _patch(monkeypatch, data)
    res = run_backtest(dict(BASE_CFG, min_score=-999.0, max_buy_pct=None,
                            filters={}),   # 关闭筛选过滤链，单独验证不追高
                       progress_cb=lambda m, p: None)
    assert res["trades"]
    assert res["trades"][0]["buy_date"] == dates[0]


# ---------- 配置校验 ----------
def test_dummy_guard():
    # 防止未来重构误删关键配置键
    from backtest import DEFAULT_BT_CONFIG
    assert DEFAULT_BT_CONFIG["stop_loss"] == -12.0
    assert DEFAULT_BT_CONFIG["take_profit"] == 20.0
    assert DEFAULT_BT_CONFIG["rebalance_every"] == 2
    assert DEFAULT_BT_CONFIG["hold_days"] == 15
    assert DEFAULT_BT_CONFIG["top_n"] == 10
    assert DEFAULT_BT_CONFIG["init_cash"] == 6000
    assert DEFAULT_BT_CONFIG["min_score"] == 48.0
    assert DEFAULT_BT_CONFIG["market_filter"] is True
    assert DEFAULT_BT_CONFIG["market_filter_mode"] == "oversold"
    assert DEFAULT_BT_CONFIG["market_rsi_threshold"] == 40.0
    assert DEFAULT_BT_CONFIG["max_buy_pct"] == 6.0


# ---------- 本金自适应持仓数 ----------
def test_fit_top_n_to_cash():
    from backtest import _fit_top_n_to_cash
    # 6000 元：顶格 10 只（每只约 600 元）
    assert _fit_top_n_to_cash(25, 6000) == 10
    assert _fit_top_n_to_cash(10, 6000) == 10
    assert _fit_top_n_to_cash(5, 6000) == 5          # 用户已手动调小则尊重
    # 大资金：不收缩
    assert _fit_top_n_to_cash(25, 1_000_000) == 25
    assert _fit_top_n_to_cash(20, 100_000) == 20
    # 更小资金：进一步收缩
    assert _fit_top_n_to_cash(25, 3000) == 5
    assert _fit_top_n_to_cash(25, 1200) == 2
    # 边界
    assert _fit_top_n_to_cash(3, 6000) == 3
    assert _fit_top_n_to_cash(25, 0) == 25


# ---------- 回测时间条件（窗口/预热天数） ----------
def test_window_auto_computes_start(monkeypatch):
    """配置 window 且未指定 start 时，自动按结束日期倒推开区间起始。"""
    data = random_market(n_days=160)
    _patch(monkeypatch, data)
    cfg = dict(BASE_CFG, start="", end="20260430", window="120", pre_days=0)
    res = run_backtest(cfg, progress_cb=lambda m, p: None)
    assert res["metrics"]["days"] >= 2


def test_pre_days_propagates_to_data_load(monkeypatch):
    """pre_days 可覆盖默认值并影响加载区间。"""
    data = random_market(n_days=160)
    _patch(monkeypatch, data)
    cfg = dict(BASE_CFG, start="20260101", end="20260430", pre_days=10)
    res = run_backtest(cfg, progress_cb=lambda m, p: None)
    assert res["metrics"]["days"] >= 2


# ---------- 全量回测（不抽样） ----------
def test_sampled_universe_full_when_max_codes_zero(monkeypatch):
    """max_codes<=0 表示全量回测：不抽样，返回全部标的。"""
    from backtest import _sampled_universe
    fake = {"600000": [{"date": "2024-01-01"}],
            "600001": [{"date": "2024-01-01"}],
            "600002": [{"date": "2024-01-01"}]}
    monkeypatch.setattr("backtest.load_market_rows", lambda *a, **k: fake)
    monkeypatch.setattr("backtest._default_start", lambda *a, **k: "2024-01-01")
    monkeypatch.setattr("backtest._latest_end", lambda *a, **k: "2024-12-31")
    assert _sampled_universe(["60*"], 0) == ["600000", "600001", "600002"]
    assert _sampled_universe(["60*"], -1) == ["600000", "600001", "600002"]


def test_sampled_universe_still_samples_positive(monkeypatch):
    """max_codes>0 且少于标的数时仍然抽样（抽样数量受控）。"""
    from backtest import _sampled_universe
    fake = {f"6000{i:02d}": [{"date": "2024-01-01"}] for i in range(20)}
    monkeypatch.setattr("backtest.load_market_rows", lambda *a, **k: fake)
    monkeypatch.setattr("backtest._default_start", lambda *a, **k: "2024-01-01")
    monkeypatch.setattr("backtest._latest_end", lambda *a, **k: "2024-12-31")
    out = _sampled_universe(["60*"], 5)
    assert len(out) == 5
    assert len(set(out)) == 5


# ---------- 回测买入判定与扫描共用 evaluate_buy ----------
def test_backtest_buy_uses_shared_evaluate_buy(monkeypatch):
    """回测买入段必须走 screen_common.evaluate_buy（而非内联重复实现），
    保证扫描/回测两端判定逻辑完全一致。"""
    import backtest
    calls = []
    real = backtest.evaluate_buy

    def spy(code, valid, ind, online, filters, market_ok, max_buy_pct,
            strat_hit, score=0.0, warnings=None):
        calls.append(dict(online=online, market_ok=market_ok,
                          max_buy_pct=max_buy_pct))
        return real(code, valid, ind, online, filters, market_ok,
                    max_buy_pct, strat_hit, score=score, warnings=warnings)

    monkeypatch.setattr("backtest.evaluate_buy", spy)
    _patch(monkeypatch, market_data({
        "000001": [10.0] * 60,
        "000002": [10.0] * 60,
    }))
    res = run_backtest(
        dict(BASE_CFG, min_score=-999.0, market_filter=False,
             max_buy_pct=6.0),
        progress_cb=lambda m, p: None)
    assert calls, "回测买入段必须调用共享 evaluate_buy"
    assert all(c["online"] == {} for c in calls), "回测无历史在线数据，online 恒为 {}"
    assert all(c["market_ok"] for c in calls), "market_filter=False 时大盘恒放行"
    assert all(c["max_buy_pct"] == 6.0 for c in calls), "max_buy_pct 应原样透传"
    assert res["trades"], "应产生买入"


def test_backtest_buy_respects_evaluate_buy_no_chase(monkeypatch):
    """回测不追高由 evaluate_buy 统一判定：当日 pct_chg 超阈值不买入。"""
    import backtest
    blocked = []
    real = backtest.evaluate_buy

    def spy(code, valid, ind, online, filters, market_ok, max_buy_pct,
            strat_hit, score=0.0, warnings=None):
        v = real(code, valid, ind, online, filters, market_ok,
                 max_buy_pct, strat_hit, score=score, warnings=warnings)
        if not v["no_chase_ok"]:
            blocked.append(code)
        return v

    monkeypatch.setattr("backtest.evaluate_buy", spy)
    data = market_data({"A": [10.0] * 60, "B": [10.0] * 60})
    data["A"][0]["pct_chg"] = 8.0
    dates = trading_dates(60)
    _patch(monkeypatch, data)
    res = run_backtest(
        dict(BASE_CFG, min_score=-999.0, max_buy_pct=6.0, filters={}),
        progress_cb=lambda m, p: None)
    assert "A" in blocked, "高涨幅股票当日应被不追高判定拦截"
    tb = [t for t in res["trades"] if t["code"] == "B"]
    assert tb and tb[0]["buy_date"] == dates[0]


# ---------- 扫描端大盘过滤（与回测同口径：全池等权指数） ----------
def _idx_rows(closes):
    """把一组收盘价序列包装成 rows_by_code（单只股票即为等权指数）。"""
    from tests.conftest import closes_to_rows, trading_dates
    return {"000001": closes_to_rows(closes, code="000001",
                                     dates=trading_dates(len(closes)))}


def test_scan_market_ok_no_data_returns_true():
    """无任何K线数据时大盘过滤放行，避免误伤。"""
    from backtest import scan_market_ok
    assert scan_market_ok({}) is True


def test_scan_market_ok_uptrend_strong_allows():
    """指数单边上行且站上 MA20：strong 模式允许买入。"""
    from backtest import scan_market_ok
    closes = [10 + i * 0.2 for i in range(30)]   # 10 → 15.8 单边上行
    assert scan_market_ok(_idx_rows(closes), mode="strong") is True


def test_scan_market_ok_downtrend_strong_blocks():
    """指数单边下行（低于 MA20）：strong 模式禁止买入。"""
    from backtest import scan_market_ok
    closes = [15 - i * 0.2 for i in range(30)]   # 15 → 9.2 单边下行
    assert scan_market_ok(_idx_rows(closes), mode="strong") is False


def test_scan_market_ok_flat_strong_blocks():
    """指数横盘（MA20 走平）：strong 模式要求 MA20 上行，不放行。"""
    from backtest import scan_market_ok
    closes = [10.0] * 30
    assert scan_market_ok(_idx_rows(closes), mode="strong") is False


def test_scan_market_ok_downtrend_oversold_allows():
    """指数单边下行（RSI 超卖<40）：oversold 模式放行买入。"""
    from backtest import scan_market_ok
    closes = [15 - i * 0.2 for i in range(30)]
    assert scan_market_ok(_idx_rows(closes), mode="oversold",
                          rsi_threshold=40.0) is True


def test_scan_market_ok_uptrend_oversold_blocks():
    """指数单边上行（RSI 高位≥40）：oversold 模式禁止买入。"""
    from backtest import scan_market_ok
    closes = [10 + i * 0.2 for i in range(30)]
    assert scan_market_ok(_idx_rows(closes), mode="oversold",
                          rsi_threshold=40.0) is False


def test_scan_market_ok_forwards_mode_and_up_days(monkeypatch):
    """scan_market_ok 将 mode/up_days/rsi_threshold/深度条件 原样转发给
    _market_ok，供 main.py 按 DEFAULT_BT_CONFIG 传入，保证两端大盘口径一致。"""
    from backtest import scan_market_ok
    seen = {}

    def fake_market_ok(mc, mma, di, enabled, mode, up_days, rsi_threshold,
                       chg20_max, chg20_max2, chg60_min):
        seen.update(mode=mode, up_days=up_days, enabled=enabled,
                    rsi_threshold=rsi_threshold, chg20_max=chg20_max,
                    chg20_max2=chg20_max2, chg60_min=chg60_min)
        return True

    monkeypatch.setattr("backtest._market_ok", fake_market_ok)
    closes = [10 + i * 0.1 for i in range(30)]
    assert scan_market_ok(_idx_rows(closes), mode="above", up_days=5,
                          rsi_threshold=35.0) is True
    assert seen == {"mode": "above", "up_days": 5, "enabled": True,
                    "rsi_threshold": 35.0, "chg20_max": None,
                    "chg20_max2": None, "chg60_min": None}
    assert scan_market_ok(_idx_rows(closes), mode="oversold", up_days=5,
                          rsi_threshold=40.0, chg20_max=-14.0,
                          chg20_max2=-10.0, chg60_min=0.0) is True
    assert seen == {"mode": "oversold", "up_days": 5, "enabled": True,
                    "rsi_threshold": 40.0, "chg20_max": -14.0,
                    "chg20_max2": -10.0, "chg60_min": 0.0}


def test_scan_market_ok_mode_above_allows_flat():
    """mode='above' 仅要求指数高于 MA20：横盘时放行（与 strong 区分）。"""
    from backtest import scan_market_ok
    closes = [10.0] * 30
    assert scan_market_ok(_idx_rows(closes), mode="above") is True
