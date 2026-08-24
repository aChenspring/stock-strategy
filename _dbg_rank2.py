# -*- coding: utf-8 -*-
"""按日排名：每日 score 最低K名（升序）vs 全体候选 fwd20。"""
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

all_fwd = [f for v in by_day.values() for _, f in v]
print(f"全体候选 n={len(all_fwd)} fwd20={sum(all_fwd)/len(all_fwd):.2f}%")

# 升序（最低分先选）
for K in (1, 2, 3, 5, 8, 10):
    fwds = []
    for date, v in by_day.items():
        v.sort(key=lambda x: x[0])   # 升序
        fwds += [f for _, f in v[:K]]
    w = sum(1 for x in fwds if x > 0) / len(fwds) * 100
    print(f"每日最低{K}名(升序) n={len(fwds)} fwd20={sum(fwds)/len(fwds):.2f}% win={w:.1f}%")

# 每日内随机抽K
import random
random.seed(1)
for K in (5, 10):
    fwds = []
    for date, v in by_day.items():
        if len(v) < K:
            picks = v
        else:
            picks = random.sample(v, K)
        fwds += [f for _, f in picks]
    print(f"每日随机{K}只 n={len(fwds)} fwd20={sum(fwds)/len(fwds):.2f}%")

print(f"耗时 {time.time()-t0:.0f}s")
