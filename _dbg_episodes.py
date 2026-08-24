# -*- coding: utf-8 -*-
"""各深度超卖日：候选池 fwd20 分布 vs 前8名 fwd20。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _latest_end,
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
pre_start = "20190101"
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
print(f"股票 {len(series_map)} 耗时 {time.time()-t0:.0f}s")

TARGETS = ["20220421", "20220427", "20240130", "20240201", "20250409", "20260720"]
max_buy_pct = c.get("max_buy_pct") or None

for date in TARGETS:
    pool = []
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                     48.0, defs_full, rmap, True, "factor_default")
        if r is None:
            continue
        # 前瞻20日
        i = s.index_at(date)
        dts = s.dates
        if i < 0 or i + 20 >= len(dts):
            continue
        px = s._data["close"][i]
        px20 = s._data["close"][i + 20]
        fwd = (px20 / px - 1) * 100 if px and px20 else None
        pool.append((r["scored"]["total"], code, fwd))
    if not pool:
        print(f"{date}: 无候选")
        continue
    pool.sort(key=lambda x: -x[0])
    fwds = [p[2] for p in pool if p[2] is not None]
    top8 = pool[:8]
    top8_fwds = [p[2] for p in top8 if p[2] is not None]
    def avg(xs):
        return sum(xs) / len(xs) if xs else 0
    print(f"{date}: 候选{len(pool)} 全体fwd20={avg(fwds):.1f}% "
          f"前8fwd20={avg(top8_fwds):.1f}% "
          f"最高分票fwd={top8[0][2]:.1f}%")
    print(f"    前8: " + ", ".join(f"{p[1]}({p[0]:.0f}fw{p[2]:+.1f})" for p in top8))
print(f"总耗时 {time.time()-t0:.0f}s")
