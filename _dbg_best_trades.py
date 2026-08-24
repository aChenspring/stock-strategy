# -*- coding: utf-8 -*-
"""最优配置的实际成交明细。"""
import time

from backtest import run_backtest

c = dict(strategy="factor_default", start="", end="",
         universe="all", max_codes=0, pre_days=60,
         market_filter=True, market_filter_mode="oversold",
         market_rsi_threshold=40.0, max_cash_pct=1.0,
         take_profit=None, init_cash=100_000,
         market_chg20_max=-12.0, min_score=48.0, top_n=8)

t0 = time.time()
res = run_backtest(c, progress_cb=lambda m, p: None)
m = res["metrics"]
print(f"total={m.get('total_return', 0):.2f}% trades={len(res['trades'])} "
      f"win={m.get('win_rate', 0):.1f}% md={m.get('max_drawdown', 0):.1f}%")
print(f"耗时 {time.time()-t0:.0f}s")
print(f"{'code':8s} {'买日':10s} {'卖日':10s} {'买价':>7s} {'卖价':>7s} {'pnl%':>7s} {'持':>3s} {'原因':8s}")
for t in sorted(res["trades"], key=lambda x: x["buy_date"]):
    print(f"{t['code']:8s} {t['buy_date']:10s} {t['sell_date']:10s} "
          f"{t['buy_price']:7.2f} {t['sell_price']:7.2f} "
          f"{t['pnl_pct']:6.2f}% {t['hold_days']:3d} {t['reason']}")
