# -*- coding: utf-8 -*-
"""score≥45 候选的多持有期前向收益（fwd3/5/8/10/15/20）。"""
import time
from collections import defaultdict

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, judge_at,
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
print(f"series={len(series_map)} axis={len(axis)}", flush=True)

max_buy_pct = c.get("max_buy_pct") or None
h = {3: [], 5: [], 8: [], 10: [], 15: [], 20: []}
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
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
        for k in h:
            j = min(i + k, s.n - 1)
            h[k].append((s._data["close"][j] / px - 1) * 100.0)

print("\nscore>=45 候选 多持有期前向收益:")
for k in sorted(h):
    arr = h[k]
    win = sum(1 for x in arr if x > 0) / len(arr) * 100
    print(f"  fwd{k:3d}: n={len(arr):6d} avg={sum(arr)/len(arr):6.2f}% win={win:5.1f}%")
print(f"耗时 {time.time()-t0:.0f}s")
