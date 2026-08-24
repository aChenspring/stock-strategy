# -*- coding: utf-8 -*-
"""2020窗口调参冲刺 +50%，并测试MA250趋势保护。"""
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="20200101", end="",
            universe="all", max_codes=1200, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None, init_cash=100_000,
            market_chg20_max=-12.0, min_score=48.0, top_n=8,
            hold_days=10)

CFGS = [
    dict(),                                    # 基准 +47.90%
    dict(take_profit=30.0),
    dict(top_n=12),
    dict(min_score=45.0),
    dict(hold_days=12),
    dict(top_n=12, take_profit=30.0),
    dict(hold_days=15),
    dict(take_profit=25.0),
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
