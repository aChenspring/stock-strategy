# -*- coding: utf-8 -*-
"""按每日候选数量分组：候选密度 vs fwd20，验证"候选少的日子更好"。"""
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
by_day = defaultdict(list)   # date -> [(score, fwd20)]
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
        j = min(i + 20, s.n - 1)
        fwd20 = (s._data["close"][j] / px - 1) * 100.0
        by_day[date].append((r["scored"]["total"], fwd20))

# 按每日候选数分组
dens = defaultdict(list)
for date, v in by_day.items():
    dens[len(v)].extend(f for _, f in v)

print("每日候选数 n 分布:")
for cnt in sorted(dens):
    arr = dens[cnt]
    win = sum(1 for x in arr if x > 0) / len(arr) * 100
    print(f"  {cnt:3d}只/日: 天数={sum(1 for d in by_day if len(by_day[d])==cnt):4d} "
          f"标的={len(arr):5d} fwd20={sum(arr)/len(arr):6.2f}% win={win:5.1f}%")

# 聚合桶
print("\n聚合:")
for lo, hi in [(1, 1), (2, 3), (4, 6), (7, 10), (11, 100)]:
    arr, ndays = [], 0
    for date, v in by_day.items():
        if lo <= len(v) <= hi:
            ndays += 1
            arr.extend(f for _, f in v)
    if arr:
        win = sum(1 for x in arr if x > 0) / len(arr) * 100
        print(f"  {lo}-{hi}只/日: 天数={ndays:4d} 标的={len(arr):5d} "
              f"fwd20={sum(arr)/len(arr):6.2f}% win={win:5.1f}%")
print(f"耗时 {time.time()-t0:.0f}s")
