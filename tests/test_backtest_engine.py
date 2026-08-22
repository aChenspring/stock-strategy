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
    on = run_backtest(dict(BASE_CFG, market_filter=True, min_score=-999.0),
                      progress_cb=lambda m, p: None)
    off = run_backtest(dict(BASE_CFG, market_filter=False, min_score=-999.0),
                       progress_cb=lambda m, p: None)

    # 过滤开启：MA20 明显高于指数的下跌段（d20~d35，MA20 从 9.9 降至 8.1）
    # 不得买入；MA20 追平指数后恢复买入属正常择时行为
    assert on["trades"], "预热期（MA20 未形成）允许买入"
    assert not any(dates[20] <= t["buy_date"] <= dates[35]
                   for t in on["trades"]), \
        [t["buy_date"] for t in on["trades"]]
    # 过滤关闭：下跌段会买入
    assert any(dates[20] <= t["buy_date"] <= dates[35]
               for t in off["trades"])
    # 过滤开启的总交易数更少
    assert len(on["trades"]) < len(off["trades"])


# ---------- 不追高 ----------
def test_max_buy_pct_skips_high_gain_day(monkeypatch):
    data = market_data({"A": [10.0] * 60, "B": [10.0] * 60})
    data["A"][0]["pct_chg"] = 8.0   # 当日 +8% > 阈值 6
    data["B"][0]["pct_chg"] = -2.0
    dates = trading_dates(60)

    _patch(monkeypatch, data)
    res = run_backtest(dict(BASE_CFG, min_score=-999.0, max_buy_pct=6.0),
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
    res = run_backtest(dict(BASE_CFG, min_score=-999.0, max_buy_pct=None),
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
    assert DEFAULT_BT_CONFIG["min_score"] == 55.0
    assert DEFAULT_BT_CONFIG["market_filter"] is True
    assert DEFAULT_BT_CONFIG["market_filter_mode"] == "strong"
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
