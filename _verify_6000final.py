# -*- coding: utf-8 -*-
"""6000元 + 最终双规则策略。"""
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="20200101", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None, init_cash=6000,
            min_score=48.0, top_n=8, hold_days=12,
            market_chg20_max=-14.0, market_chg20_max2=-10.0, market_chg60_min=0.0)

CFGS = [
    dict(),
    dict(top_n=5),
    dict(top_n=3),
    dict(top_n=5, min_score=45.0),
    dict(top_n=5, hold_days=15),
]

for i, extra in enumerate(CFGS):
    c = dict(BASE)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        print(f"[{i}] {extra}")
        print(f"    total={m.get('total_return', 0):.2f}% "
              f"annual={m.get('annual_return', 0):.2f}% "
              f"trades={len(res['trades'])} "
              f"win={m.get('win_rate', 0):.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"md={m.get('max_drawdown', 0):.1f}% "
              f"elapsed={time.time()-t0:.0f}s")
    except Exception as e:
        print(f"[{i}] {extra} ERROR: {e}")
