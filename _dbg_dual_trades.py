# -*- coding: utf-8 -*-
"""双规则配置成交明细（区分主/次规则触发日）。"""
import time

from backtest import run_backtest

c = dict(strategy="factor_default", start="20200101", end="",
         universe="all", max_codes=0, pre_days=60,
         market_filter=True, market_filter_mode="oversold",
         market_rsi_threshold=40.0, max_cash_pct=1.0,
         take_profit=None, init_cash=100_000,
         min_score=48.0, top_n=8, hold_days=12,
         market_chg20_max=-14.0, market_chg20_max2=-10.0, market_chg60_min=0.0)

t0 = time.time()
res = run_backtest(c, progress_cb=lambda m, p: None)
m = res["metrics"]
print(f"total={m.get('total_return', 0):.2f}% trades={len(res['trades'])} "
      f"win={m.get('win_rate', 0):.1f}% md={m.get('max_drawdown', 0):.1f}%")
print(f"耗时 {time.time()-t0:.0f}s")
by_day = {}
for t in res["trades"]:
    by_day.setdefault(t["buy_date"], []).append(t)
for d in sorted(by_day):
    ts = by_day[d]
    pnls = [t["pnl_pct"] for t in ts]
    print(f"{d}: {len(ts)}笔  平均pnl={sum(pnls)/len(pnls):.1f}%  "
          f"明细=" + ", ".join(f"{t['code']}:{t['pnl_pct']:+.1f}" for t in ts))
