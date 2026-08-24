# -*- coding: utf-8 -*-
"""对比 100k 与 6000 资金的实际成交差异。"""
import time

from backtest import run_backtest

for cash in (6000, 100_000):
    c = dict(strategy="factor_default", start="", end="", universe="all",
             max_codes=0, pre_days=60, market_filter=False, min_score=45.0,
             init_cash=cash)
    t0 = time.time()
    res = run_backtest(c, progress_cb=lambda m, p: None)
    m = res["metrics"]
    print(f"\n===== cash={cash} total={m.get('total_return', 0):.2f}% "
          f"trades={len(res['trades'])} elapsed={time.time()-t0:.0f}s =====")
    by_date = {}
    for t in res["trades"]:
        by_date.setdefault(t["buy_date"], []).append(t)
    for d in sorted(by_date):
        ts = by_date[d]
        r = sum(t["pnl_pct"] for t in ts) / len(ts)
        print(f"  {d}: {len(ts)}只 avg_pnl={r:6.2f}%")
    wins = [t for t in res["trades"] if t["pnl_pct"] > 0]
    losses = [t for t in res["trades"] if t["pnl_pct"] <= 0]
    wa = sum(t["pnl_pct"] for t in wins) / max(1, len(wins))
    la = sum(t["pnl_pct"] for t in losses) / max(1, len(losses))
    print(f"  盈 {len(wins)} avg={wa:.2f}%  亏 {len(losses)} avg={la:.2f}%")
    # 每股持仓金额/股数分布
    sizes = [t.get("shares", 0) * t.get("buy_price", 0) for t in res["trades"]]
    prices = [t.get("buy_price", 0) for t in res["trades"]]
    print(f"  平均单笔金额={sum(sizes)/len(sizes):.0f} 中位股价={sorted(prices)[len(prices)//2]:.2f} "
          f"股价<6占比={sum(1 for p in prices if p < 6)/len(prices)*100:.0f}%")
