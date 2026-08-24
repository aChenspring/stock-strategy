# -*- coding: utf-8 -*-
"""指标计算正确性测试：SMA / RSI / MACD / KDJ / 上下文字段。"""
from backtest import _sma, _rsi, _macd, _kdj, _market_ok
from backtest import IndicatorSeries
from tests.conftest import closes_to_rows, trading_dates


# ---------- 指标 ----------
def test_sma_basic():
    assert _sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_empty():
    assert _sma([], 3) == []


def test_rsi_all_up():
    # 连续上涨 -> RSI 恒为 100
    r = _rsi([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 6)
    assert r[:6] == [None] * 6
    assert all(v == 100.0 for v in r[6:])


def test_rsi_all_down():
    r = _rsi([10, 9, 8, 7, 6, 5, 4, 3, 2, 1], 6)
    assert r[:6] == [None] * 6
    assert all(v == 0.0 for v in r[6:])


def test_rsi_mixed_range():
    # 混合涨跌：RSI 应在 0~100 之间
    r = _rsi([5, 6, 5, 7, 6, 8, 7, 9, 8, 10, 9, 11], 6)
    vals = [v for v in r if v is not None]
    assert vals
    assert all(0.0 <= v <= 100.0 for v in vals)


def test_macd_length_and_nan():
    closes = list(range(1, 80))
    m = _macd(closes)
    assert len(m) == len(closes)
    # 前段无 EMA26 数据时输出 0（引擎自行兜底），后段应出现非 0
    assert any(abs(v) > 0.0 for v in m[-10:])


def test_kdj_range():
    highs = [10 + i % 5 for i in range(60)]
    lows = [8 + i % 3 for i in range(60)]
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    k, d = _kdj(highs, lows, closes)
    assert len(k) == 60 and len(d) == 60
    assert all(0 <= v <= 100 for v in k)
    assert all(0 <= v <= 100 for v in d)


# ---------- 过滤逻辑（纯函数） ----------
def test_market_ok_disabled():
    assert _market_ok([1.0], [2.0], 0, enabled=False) is True


def test_market_ok_above_ma():
    assert _market_ok([11.0], [10.0], 0, enabled=True) is True


def test_market_ok_below_ma():
    assert _market_ok([9.0], [10.0], 0, enabled=True) is False


def test_market_ok_missing_data():
    assert _market_ok([None], [10.0], 0, enabled=True) is True
    assert _market_ok([9.0], [], 0, enabled=True) is True


# ---------- 大盘过滤模式：above / strong ----------
def test_market_ok_above_mode_allows_ma_up_and_down():
    # 指数在 20 日线上方即可，MA20 方向不影响
    up = [10.0, 10.2, 10.4, 10.6]
    assert _market_ok([11.0, 11.0, 11.0, 11.0], up, 3,
                      enabled=True, mode="above") is True
    down = [10.6, 10.4, 10.2, 10.0]
    assert _market_ok([11.0, 11.0, 11.0, 11.0], down, 3,
                      enabled=True, mode="above") is True


def test_market_ok_strong_requires_ma_up():
    # MA20 上行 + 指数在上方 -> 放行
    up = [10.0, 10.2, 10.4, 10.6]
    assert _market_ok([11.0, 11.0, 11.0, 11.0], up, 3,
                      enabled=True, mode="strong", up_days=3) is True
    # MA20 下行 + 指数在上方 -> 不放行
    down = [10.6, 10.4, 10.2, 10.0]
    assert _market_ok([11.0, 11.0, 11.0, 11.0], down, 3,
                      enabled=True, mode="strong", up_days=3) is False
    # MA20 横盘 -> 不放行
    flat = [10.0, 10.0, 10.0, 10.0]
    assert _market_ok([11.0, 11.0, 11.0, 11.0], flat, 3,
                      enabled=True, mode="strong", up_days=3) is False
    # up_days=1（只看前一日）：MA20 当日低于前一日 -> 不放行
    assert _market_ok([11.0, 11.0, 11.0, 11.0], down, 3,
                      enabled=True, mode="strong", up_days=1) is False


def test_market_ok_strong_lookback_missing():
    # 回看起点无数据（MA20 刚形成）：退化为只要求指数在线上方
    mma = [None] * 19 + [10.0, 10.1, 10.2]
    assert _market_ok([11.0] * 22, mma, 21,
                      enabled=True, mode="strong", up_days=3) is True
    # 但指数跌破 MA20 时仍不放行
    assert _market_ok([9.0] * 22, mma, 21,
                      enabled=True, mode="strong", up_days=3) is False


# ---------- IndicatorSeries ----------
def test_series_ctx_fields():
    closes = [10.0] * 30 + [11.0, 12.0, 11.5]
    dates = trading_dates(len(closes))
    rows = closes_to_rows(closes, dates=dates)
    s = IndicatorSeries("000001", rows)
    assert s.n == len(closes)
    assert s.has_date(dates[10])
    ctx = s.ctx_at(dates[-1])
    assert ctx is not None
    for key in ("close", "pct", "ma5", "ma10", "ma20", "macd", "rsi6",
                "k", "d", "vol_ratio", "limit_up_5", "is_break",
                "bull_arrange", "profit_ratio"):
        assert key in ctx, key


def test_series_ctx_exact_missing_date():
    rows = closes_to_rows([10.0] * 30, dates=trading_dates(30))
    s = IndicatorSeries("000001", rows)
    assert s.has_date("20260101")
    # 停牌日（周六）精确取返回 None
    assert s.ctx_at("20260103", exact=True) is None


def test_series_indicator_at():
    rows = closes_to_rows([10.0] * 30, dates=trading_dates(30))
    s = IndicatorSeries("000001", rows)
    ind = s.indicator_at("20260130")
    assert {"ma5", "ma10", "ma20", "ma60", "rsi6", "k", "d", "close"} <= set(ind)
