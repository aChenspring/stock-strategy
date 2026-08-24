# -*- coding: utf-8 -*-
"""抽样扫描 2023-2026：所有 RSI<40 且 chg20<-12 的交易日。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _latest_end, IndicatorSeries,
    _market_rsi,
)
from strategy_data import A_SHARE_PREFIXES

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, 1500)
rows_map = _load_rows(universe, "20220101", _latest_end())
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
print(f"股票数 {len(series_map)} 加载耗时 {time.time()-t0:.0f}s")

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

print(f"{'日期':10s} {'RSI':>4s} {'chg5':>6s} {'chg20':>6s} {'chg60':>6s} "
      f"{'距120d高':>8s} {'距60d高':>7s} {'fwd10':>6s} {'fwd20':>6s}")
n = 0
for j in range(len(market_close)):
    r = _market_rsi(market_close, 14, j)
    if r is None or r >= 40:
        continue
    mc = market_close[j]
    if j < 20 or market_close[j-20] is None:
        continue
    chg20 = (mc / market_close[j-20] - 1) * 100
    if chg20 >= -12:
        continue
    def chg(nd):
        return (mc / market_close[j-nd] - 1) * 100 if j >= nd and market_close[j-nd] else 0.0
    hi60 = max(market_close[max(0, j-60):j+1])
    hi120 = max(market_close[max(0, j-120):j+1])
    fwd10 = (market_close[j+10] / mc - 1) * 100 if j+10 < len(market_close) else None
    fwd20 = (market_close[j+20] / mc - 1) * 100 if j+20 < len(market_close) else None
    print(f"{dates_all[j]:10s} {r:4.0f} {chg(5):6.1f} {chg20:6.1f} "
          f"{chg(60):6.1f} {(mc/hi120-1)*100:7.1f}% {(mc/hi60-1)*100:6.1f}% "
          f"{fwd10 if fwd10 is not None else 0:6.1f} {fwd20 if fwd20 is not None else 0:6.1f}")
    n += 1
print(f"共 {n} 天  耗时 {time.time()-t0:.0f}s")
