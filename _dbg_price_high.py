# -*- coding: utf-8 -*-
"""score>=45 候选按股价分组的 fwd15/fwd20，验证低价因子。"""
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

max_buy_pct = c.get("max_buy_pct") or None
groups = defaultdict(lambda: {"f15": [], "f20": []})
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
        d = s._data
        px = d["close"][i]
        if not px:
            continue
        f15 = (d["close"][min(i+15, s.n-1)] / px - 1) * 100
        f20 = (d["close"][min(i+20, s.n-1)] / px - 1) * 100
        if px < 3:
            g = "<3"
        elif px < 5:
            g = "3-5"
        elif px < 8:
            g = "5-8"
        elif px < 12:
            g = "8-12"
        else:
            g = ">=12"
        groups[g]["f15"].append(f15)
        groups[g]["f20"].append(f20)

print("\nscore>=45 候选按股价分组:")
print(f"{'px':6s} {'n':6s} {'fwd15':8s} {'win15':6s} {'fwd20':8s} {'win20':6s}")
for g in ["<3", "3-5", "5-8", "8-12", ">=12"]:
    d = groups[g]
    a15 = sum(d["f15"]) / len(d["f15"]) if d["f15"] else 0
    a20 = sum(d["f20"]) / len(d["f20"]) if d["f20"] else 0
    w15 = sum(1 for x in d["f15"] if x > 0) / len(d["f15"]) * 100 if d["f15"] else 0
    w20 = sum(1 for x in d["f20"] if x > 0) / len(d["f20"]) * 100 if d["f20"] else 0
    print(f"{g:6s} {len(d['f15']):6d} {a15:8.2f} {w15:6.1f} {a20:8.2f} {w20:6.1f}")
print(f"耗时 {time.time()-t0:.0f}s")
