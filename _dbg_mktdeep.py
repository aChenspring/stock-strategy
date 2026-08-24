# -*- coding: utf-8 -*-
"""RSI<40 的调仓日：大盘 chg20/chg5 与候选 fwd20 的关系。"""
import time
from collections import defaultdict

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, judge_at, _market_rsi,
)
from screen_common import DEFAULT_SCAN_FILTERS
from strategy_data import A_SHARE_PREFIXES
from strategy_schema import build_factor_defs, build_rules_map

c = dict(DEFAULT_BT_CONFIG)
c.update(max_codes=0, pre_days=60)
defs_full = build_factor_defs(c.get("config"))
rmap = build_rules_map(c.get("config"))

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 120 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
axis = _market_axis(series_map, c["start"], dates_end)

market_close = []
last_mc = None
for date in axis:
    cs = [s._data["close"][s.index_at(date)] for s in series_map.values()
          if s.index_at(date) >= 0]
    v = sum(cs) / len(cs) if cs else last_mc
    last_mc = v
    market_close.append(v)

max_buy_pct = c.get("max_buy_pct") or None
print(f"{'date':10s} {'RSI':5s} {'chg20':7s} {'chg5':6s} {'候选':5s} {'fwd20':7s}")
rows = []
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    rsi = _market_rsi(market_close, 14, di)
    if rsi is None or rsi >= 40:
        continue
    mc = market_close[di]
    chg20 = (mc / market_close[max(0, di-20)] - 1) * 100
    chg5 = (mc / market_close[max(0, di-5)] - 1) * 100
    recs = []
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                     45.0, defs_full, rmap, True, "factor_default")
        if r is None:
            continue
        i = s.index_at(date)
        px = s._data["close"][i]
        if not px:
            continue
        j = min(i + 20, s.n - 1)
        recs.append((s._data["close"][j] / px - 1) * 100.0)
    if not recs:
        continue
    f = sum(recs) / len(recs)
    rows.append((date, rsi, chg20, chg5, len(recs), f))
    print(f"{date:10s} {rsi:5.0f} {chg20:7.1f} {chg5:6.1f} {len(recs):5d} {f:7.2f}")

# 分组
print("\n按 chg20 深度分组:")
for lo, hi in [(-99, -15), (-15, -10), (-10, -5), (-5, 99)]:
    sub = [r for r in rows if lo <= r[2] < hi]
    if sub:
        fwds = [r[5] for r in sub]
        print(f"  chg20 {lo}~{hi}: 天数={len(sub)} fwd20={sum(fwds)/len(fwds):6.2f}%")
print(f"耗时 {time.time()-t0:.0f}s")
