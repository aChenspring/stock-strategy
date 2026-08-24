# -*- coding: utf-8 -*-
"""全量指数：次规则候选日（RSI<40 且 -14<chg20<-6）的 chg60 分布。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _latest_end, IndicatorSeries,
    _market_rsi,
)
from strategy_data import A_SHARE_PREFIXES

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, 0)
rows_map = _load_rows(universe, "20190101", _latest_end())
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
print(f"股票数 {len(series_map)} 加载 {time.time()-t0:.0f}s")

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

print(f"{'日期':10s} {'RSI':>4s} {'chg20':>6s} {'chg60':>6s}")
for j in range(len(market_close)):
    r = _market_rsi(market_close, 14, j)
    if r is None or r >= 40:
        continue
    mc = market_close[j]
    if j < 60 or market_close[j-60] is None or market_close[j-20] is None:
        continue
    chg20 = (mc / market_close[j-20] - 1) * 100
    if not (-14 <= chg20 < -6):
        continue
    chg60 = (mc / market_close[j-60] - 1) * 100
    print(f"{dates_all[j]:10s} {r:4.0f} {chg20:6.1f} {chg60:6.1f}")
print(f"耗时 {time.time()-t0:.0f}s")
