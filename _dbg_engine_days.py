# -*- coding: utf-8 -*-
"""用引擎的 _market_ok 判定每个调仓日是否放行（对比候选数）。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, judge_at, _market_ok, _sma,
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

# 与引擎一致：market_close / market_ma20
closes_by_date = {}
for s in series_map.values():
    for i, d in enumerate(s.dates):
        closes_by_date.setdefault(d, []).append(s._data["close"][i])
dates_all = sorted(closes_by_date)
market_close = []
last = None
for d in dates_all:
    cs = closes_by_date[d]
    v = sum(cs) / len(cs) if cs else last
    last = v
    market_close.append(v)
idx = {d: i for i, d in enumerate(dates_all)}
ma20 = _sma([v if v is not None else 0.0 for v in market_close], 20)

max_buy_pct = c.get("max_buy_pct") or None
print(f"{'date':10s} {'RSI':5s} {'chg20':7s} {'ok_-8':6s} {'ok_-10':6s} {'ok_-12':6s} {'候选':5s}")
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    j = idx.get(date)
    if j is None:
        continue
    ok8 = _market_ok(market_close, ma20, j, True, "oversold", 3, 40.0, -8.0)
    ok10 = _market_ok(market_close, ma20, j, True, "oversold", 3, 40.0, -10.0)
    ok12 = _market_ok(market_close, ma20, j, True, "oversold", 3, 40.0, -12.0)
    if not (ok8 or ok10 or ok12):
        continue
    chg20 = (market_close[j] / market_close[j-20] - 1) * 100
    rsi = 0
    for k in range(1, 15):
        ch = market_close[j-k+1] - market_close[j-k]
    # 粗略打印
    n_cand = 0
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                     45.0, defs_full, rmap, True, "factor_default")
        if r is not None:
            n_cand += 1
    print(f"{date:10s} {chg20:7.1f} {'Y' if ok8 else '-':6s} "
          f"{'Y' if ok10 else '-':6s} {'Y' if ok12 else '-':6s} {n_cand:5d}")
print(f"耗时 {time.time()-t0:.0f}s")
