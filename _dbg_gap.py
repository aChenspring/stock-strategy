# -*- coding: utf-8 -*-
"""对比：引擎实现收益 vs 同批股票原始 fwd20。
用 no-stop/no-tp/hold20 配置，比较 realized vs raw fwd20。
"""
import time

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, run_backtest,
)
from strategy_data import A_SHARE_PREFIXES

c = dict(strategy="factor_default", start="", end="", universe="all",
         max_codes=0, pre_days=60, market_filter=False, min_score=45.0,
         init_cash=100_000, stop_loss=None, take_profit=None, hold_days=20)

t0 = time.time()
res = run_backtest(c, progress_cb=lambda m, p: None)
m = res["metrics"]
print(f"total={m.get('total_return', 0):.2f}% trades={len(res['trades'])} "
      f"elapsed={time.time()-t0:.0f}s")

# 重建 series 用于 fwd20 计算
universe = _sampled_universe(A_SHARE_PREFIXES, 0)
dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 120 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
axis = _market_axis(series_map, c["start"], dates_end)

n_diff = 0
sum_diff = 0.0
for t in res["trades"]:
    s = series_map.get(t["code"])
    if s is None:
        continue
    di = s.index_at(t["buy_date"])
    if di < 0:
        continue
    px = s._data["close"][di]
    j = min(di + 20, s.n - 1)
    fwd20 = (s._data["close"][j] / px - 1) * 100.0
    diff = fwd20 - t["pnl_pct"]
    n_diff += 1
    sum_diff += diff
    if abs(diff) > 2:
        print(f"  {t['code']} {t['buy_date']} buy={t['buy_price']:.2f} "
              f"realized={t['pnl_pct']:6.2f}% fwd20={fwd20:6.2f}% "
              f"diff={diff:6.2f}% sell={t.get('sell_date','')} "
              f"hold={t.get('hold_days','')}d")
print(f"\n平均 diff(realized - fwd20) = {sum_diff/max(1,n_diff):.2f}% (n={n_diff})")
