# -*- coding: utf-8 -*-
"""任务4同口径诊断：start=20200101, max_codes=0, min_score=55, oversold(-14/-10/0)
统计每个调仓日 _market_ok 放行情况与 55 分候选数，定位 0 交易原因。"""
import time
from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, judge_at, _market_rsi, _market_ok, _sma,
)
from screen_common import DEFAULT_SCAN_FILTERS
from strategy_data import A_SHARE_PREFIXES
from strategy_schema import build_factor_defs, build_rules_map

cfg = {
    "init_cash": 6000, "top_n": 10, "hold_days": 15, "min_score": 55,
    "stop_loss": -12, "take_profit": 20, "rebalance_every": 2,
    "max_buy_pct": 6, "market_filter_mode": "oversold",
    "market_chg20_max": -14, "market_chg20_max2": -10, "market_chg60_min": 0,
    "max_codes": 0, "start": "20200101",
}
c = dict(DEFAULT_BT_CONFIG)
c.update(cfg)

t0 = time.time()
defs_full = build_factor_defs(c.get("config"))
rmap = build_rules_map(c.get("config"))

universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
dates_end = c["end"] or _latest_end()
pre_start = _default_start(c["start"], c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
axis = _market_axis(series_map, c["start"], dates_end)
print(f"universe={len(universe)} series={len(series_map)} axis={len(axis)} "
      f"start={axis[0] if axis else '-'} end={axis[-1] if axis else '-'}", flush=True)

market_close = []
last_mc = None
for date in axis:
    cs = [s._data["close"][s.index_at(date)] for s in series_map.values()
          if s.index_at(date) >= 0]
    v = sum(cs) / len(cs) if cs else last_mc
    last_mc = v
    market_close.append(v)
market_ma20 = _sma([v if v is not None else 0.0 for v in market_close], 20)

max_buy_pct = c.get("max_buy_pct") or None
n_ok = 0
print(f"{'date':10s} {'RSI':5s} {'chg20':7s} {'chg60':7s} {'ok':5s} {'cand55':6s}")
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    ok = _market_ok(market_close, market_ma20, di,
                    c.get("market_filter", True),
                    c.get("market_filter_mode", "strong"),
                    c.get("ma_up_days", 3),
                    c.get("market_rsi_threshold", 40.0),
                    c.get("market_chg20_max"),
                    c.get("market_chg20_max2"),
                    c.get("market_chg60_min"))
    if not ok:
        continue
    n_ok += 1
    mc = market_close[di]
    rsi = _market_rsi(market_close, 14, di)
    chg20 = (mc / market_close[di - 20] - 1) * 100 if di >= 20 else float('nan')
    chg60 = (mc / market_close[di - 60] - 1) * 100 if di >= 60 else float('nan')
    n55 = n50 = n45 = 0
    mx = 0.0
    argmax = ""
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        # min_score=0：只要通过过滤链即统计，观察总分分布
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                     0.0, defs_full, rmap, True, "factor_default")
        if r is None:
            continue
        t = r["scored"]["total"]
        if t >= 55: n55 += 1
        if t >= 50: n50 += 1
        if t >= 45: n45 += 1
        if t > mx: mx, argmax = t, code
    print(f"{date:10s} {rsi:5.1f} {chg20:7.1f} {chg60:7.1f} {str(ok):5s} "
          f"n55={n55:3d} n50={n50:3d} n45={n45:3d} top={mx:.1f}@{argmax}", flush=True)
print(f"\n放行调仓日共 {n_ok} 个  耗时 {time.time()-t0:.0f}s")
