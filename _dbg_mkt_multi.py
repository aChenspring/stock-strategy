# -*- coding: utf-8 -*-
"""大盘超卖日的多尺度指标：chg5/chg10/chg20/chg60/距60日高/距120日高 + fwd10/fwd20。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, _market_rsi,
)
from strategy_data import A_SHARE_PREFIXES

c = dict(DEFAULT_BT_CONFIG)
c.update(max_codes=0, pre_days=60)

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 160 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
axis = _market_axis(series_map, c["start"], dates_end)

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

print(f"{'日期':10s} {'RSI':>4s} {'chg5':>6s} {'chg10':>6s} {'chg20':>6s} "
      f"{'chg60':>6s} {'距60d高':>7s} {'距120d高':>8s} {'fwd10':>6s} {'fwd20':>6s} {'候选≥45':>6s}")
for date in axis:
    j = idx.get(date)
    if j is None:
        continue
    r = _market_rsi(market_close, 14, j)
    if r is None or r >= 40:
        continue
    mc = market_close[j]
    def chg(nd):
        if j < nd or market_close[j-nd] is None:
            return None
        return (mc / market_close[j-nd] - 1) * 100
    hi60 = max(market_close[max(0, j-60):j+1])
    hi120 = max(market_close[max(0, j-120):j+1])
    fwd10 = fwd20 = None
    if j + 10 < len(market_close):
        fwd10 = (market_close[j+10] / mc - 1) * 100
    if j + 20 < len(market_close):
        fwd20 = (market_close[j+20] / mc - 1) * 100
    c5 = chg(5) or 0.0
    c10 = chg(10) or 0.0
    c20 = chg(20) or 0.0
    c60 = chg(60) or 0.0
    print(f"{date:10s} {r:4.0f} {c5:6.1f} {c10:6.1f} {c20:6.1f} "
          f"{c60:6.1f} {(mc/hi60-1)*100:6.1f}% {(mc/hi120-1)*100:7.1f}% "
          f"{fwd10 if fwd10 is not None else 0:6.1f} {fwd20 if fwd20 is not None else 0:6.1f}")
print(f"耗时 {time.time()-t0:.0f}s")
