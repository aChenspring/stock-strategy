# -*- coding: utf-8 -*-
"""验证：持仓集中度（top_n）对收益的影响。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=False)

CFGS = [
    # 100k + 集中持仓
    dict(min_score=45, init_cash=100_000, top_n=3),
    dict(min_score=45, init_cash=100_000, top_n=5),
    dict(min_score=48, init_cash=100_000, top_n=3),
    dict(min_score=48, init_cash=100_000, top_n=5),
    # 100k + 集中 + hold
    dict(min_score=45, init_cash=100_000, top_n=3, hold_days=12),
    dict(min_score=45, init_cash=100_000, top_n=3, hold_days=18),
    # 100k + 集中 + tp/sl
    dict(min_score=45, init_cash=100_000, top_n=3, take_profit=12.0),
    dict(min_score=45, init_cash=100_000, top_n=3, stop_loss=-8.0),
    # 6000 基准
    dict(min_score=45),
]

for i, extra in enumerate(CFGS):
    c = dict(BASE)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        print(f"[{i}] {json.dumps(extra, ensure_ascii=False)}")
        print(f"    total={m.get('total_return', 0):.2f}% "
              f"annual={m.get('annual_return', 0):.2f}% "
              f"trades={len(res['trades'])} "
              f"win={m.get('win_rate', 0)*100:.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"md={m.get('max_drawdown', 0)*100:.1f}% "
              f"elapsed={time.time()-t0:.0f}s")
    except Exception as e:
        print(f"[{i}] {json.dumps(extra, ensure_ascii=False)} ERROR: {e}")
