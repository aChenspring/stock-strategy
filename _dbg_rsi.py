# -*- coding: utf-8 -*-
"""调试：复现回测引擎的 market_close 与 RSI 判定。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, _market_ok, _market_rsi,
)
from strategy_data import A_SHARE_PREFIXES

c = dict(DEFAULT_BT_CONFIG)
c.update(max_codes=0, pre_days=60, market_filter_mode="oversold",
         market_rsi_threshold=40.0, rebalance_every=2)

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 120 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
axis = _market_axis(series_map, c["start"], dates_end)

market_close = []
last_mc = None
for date in axis:
    cs = [s._data["close"][s.index_at(date)] for s in series_map.values()
          if s.index_at(date) >= 0]
    v = sum(cs) / len(cs) if cs else last_mc
    last_mc = v
    market_close.append(v)

n_ok_all = 0
n_ok_rebal = 0
rsis = []
for di in range(len(axis)):
    r = _market_rsi(market_close, 14, di)
    rsis.append(r)
    ok = _market_ok(market_close, None, di, True, "oversold", 3, 40.0)
    if ok:
        n_ok_all += 1
        if di % c["rebalance_every"] == 0:
            n_ok_rebal += 1

valid = [r for r in rsis if r is not None]
print(f"axis={len(axis)} ({axis[0]}~{axis[-1]})")
print(f"market_close len={len(market_close)} 首={market_close[0]:.2f} 末={market_close[-1]:.2f}")
print(f"RSI 有效={len(valid)} min={min(valid):.1f} max={max(valid):.1f}")
print(f"  RSI<40 天数(全部)={sum(1 for r in rsis if r is not None and r < 40)}")
print(f"  RSI<45 天数(全部)={sum(1 for r in rsis if r is not None and r < 45)}")
print(f"  RSI<50 天数(全部)={sum(1 for r in rsis if r is not None and r < 50)}")
print(f"  market_ok=True 天数={n_ok_all} (其中调仓日 {n_ok_rebal})")
# 打印最后30个RSI
for i in range(len(rsis) - 30, len(rsis)):
    print(f"  {axis[i]} RSI={rsis[i] if rsis[i] is None else round(rsis[i],1)}")
print(f"耗时 {time.time()-t0:.0f}s")
