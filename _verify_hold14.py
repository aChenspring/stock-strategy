# -*- coding: utf-8 -*-
"""全量：2020窗口 hold13/14 + chg20_max=-14。"""
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="20200101", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None, init_cash=100_000,
            market_chg20_max=-14.0, min_score=48.0, top_n=8)

CFGS = [
    dict(hold_days=14),
    dict(hold_days=13),
]

for i, extra in enumerate(CFGS):
    c = dict(BASE)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        print(f"[{i}] hold={extra.get('hold_days')}")
        print(f"    total={m.get('total_return', 0):.2f}% "
              f"annual={m.get('annual_return', 0):.2f}% "
              f"trades={len(res['trades'])} "
              f"win={m.get('win_rate', 0):.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"md={m.get('max_drawdown', 0):.1f}% "
              f"elapsed={time.time()-t0:.0f}s")
    except Exception as e:
        print(f"[{i}] hold={extra.get('hold_days')} ERROR: {e}")
