# -*- coding: utf-8 -*-
"""检查数据时间跨度。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _latest_end,
)
from strategy_data import A_SHARE_PREFIXES

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, 0)
dates_end = _latest_end()
print("latest_end:", dates_end)
rows_map = _load_rows(universe, "2000-01-01", dates_end)
print(f"股票数: {len(rows_map)}")
d0 = None
d1 = None
total = 0
for code, rows in rows_map.items():
    if not rows:
        continue
    total += len(rows)
    a, b = rows[0]["date"], rows[-1]["date"]
    if d0 is None or a < d0:
        d0 = a
    if d1 is None or b > d1:
        d1 = b
print(f"数据范围: {d0} ~ {d1}  总行数 {total}")
print(f"耗时 {time.time()-t0:.0f}s")
