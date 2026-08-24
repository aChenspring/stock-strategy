# -*- coding: utf-8 -*-
"""调试：新规则下全市场候选分数分布。"""
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
buckets = defaultdict(int)
n_pass = {40: 0, 50: 0, 55: 0, 60: 0}
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                     -999.0, defs_full, rmap, True, "factor_default")
        if r is None:
            continue
        sc = r["scored"]["total"]
        b = int(sc // 10) * 10
        buckets[b] += 1
        for th in n_pass:
            if sc >= th:
                n_pass[th] += 1

print("分数分布（所有通过过滤链/不追高的候选）:")
for b in sorted(buckets):
    print(f"  score {b:3d}-{b+9:3d}: {buckets[b]}")
print(f"过40={n_pass[40]} 过50={n_pass[50]} 过55={n_pass[55]} 过60={n_pass[60]}")
print(f"耗时 {time.time()-t0:.0f}s")
