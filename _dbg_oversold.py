# -*- coding: utf-8 -*-
"""dump oversold 配置的成交，对比 realized vs 原始 fwd20。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    IndicatorSeries, run_backtest,
)
from strategy_data import A_SHARE_PREFIXES

c = dict(strategy="factor_default", start="", end="", universe="all",
         max_codes=0, pre_days=60, market_filter=True,
         market_filter_mode="oversold", market_rsi_threshold=40.0,
         init_cash=100_000, min_score=45.0, stop_loss=None, hold_days=25)

t0 = time.time()
res = run_backtest(c, progress_cb=lambda m, p: None)
m = res["metrics"]
print(f"total={m.get('total_return', 0):.2f}% trades={len(res['trades'])} "
      f"elapsed={time.time()-t0:.0f}s")

universe = _sampled_universe(A_SHARE_PREFIXES, 0)
dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 120 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}

by_date = {}
for t in res["trades"]:
    by_date.setdefault(t["buy_date"], []).append(t)

for d in sorted(by_date):
    ts = by_date[d]
    line = f"{d}: {len(ts)}只 "
    sum_fwd = 0.0
    n = 0
    for t in ts:
        s = series_map.get(t["code"])
        if s is None:
            continue
        di = s.index_at(t["buy_date"])
        if di < 0:
            continue
        px = s._data["close"][di]
        j = min(di + 20, s.n - 1)
        fwd20 = (s._data["close"][j] / px - 1) * 100.0
        sum_fwd += fwd20
        n += 1
        line += f"[{t['code']} r={t['pnl_pct']:+.1f}% f20={fwd20:+.1f}%] "
    if n:
        print(f"{line} avg_fwd20={sum_fwd/n:+.2f}%")
