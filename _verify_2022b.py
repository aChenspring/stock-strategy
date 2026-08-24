# -*- coding: utf-8 -*-
"""2022窗口：仓位倍率/止损/参数微调。"""
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="20220101", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None, init_cash=100_000,
            market_chg20_max=-12.0, min_score=48.0, top_n=8)

CFGS = [
    dict(hold_days=10),                                # 基准 +36.83%
    dict(hold_days=10, pos_cap_mult=1.5),
    dict(hold_days=10, pos_cap_mult=2.0),
    dict(hold_days=10, stop_loss=-10.0),
    dict(hold_days=10, max_cash_pct=0.5),
    dict(hold_days=10, min_score=45.0, top_n=12),
    dict(hold_days=10, top_n=12),
    dict(hold_days=10, pos_cap_mult=1.5, top_n=12),
    dict(hold_days=10, stop_loss=-12.0),
    dict(hold_days=10, take_profit=30.0),
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
