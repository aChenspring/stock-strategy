# -*- coding: utf-8 -*-
"""dump 最优配置的实际成交，分析收益来源。"""
import time

from backtest import run_backtest

c = dict(strategy="factor_default", start="", end="", universe="all",
         max_codes=0, pre_days=60, market_filter=False, min_score=45.0)

t0 = time.time()
res = run_backtest(c, progress_cb=lambda m, p: None)
m = res["metrics"]
print(f"total={m.get('total_return', 0):.2f}% trades={len(res['trades'])} "
      f"elapsed={time.time()-t0:.0f}s")

# 按买入日期分组
by_date = {}
for t in res["trades"]:
    by_date.setdefault(t["buy_date"], []).append(t)

print(f"\n== 买入轮次（共{len(by_date)}轮）==")
for d in sorted(by_date):
    ts = by_date[d]
    r = sum(t["pnl_pct"] for t in ts) / len(ts)
    print(f"  {d}: {len(ts)}只 avg_pnl={r:6.2f}%")

print("\n== 全部成交 ==")
print(f"{'buy_date':10s} {'code':8s} {'buy_px':6s} {'pct':6s} {'sell_date':10s} {'pnl%':7s}")
for t in res["trades"]:
    print(f"{t['buy_date']:10s} {t['code']:8s} {t.get('buy_price', 0):6.2f} "
          f"{t.get('buy_pct', 0):6.2f} {t.get('sell_date',''):10s} {t['pnl_pct']:7.2f}")
