# -*- coding: utf-8 -*-
"""围绕 chg20_max=-12 + take_profit=None 的精细网格。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, init_cash=100_000,
            max_cash_pct=1.0, market_chg20_max=-12.0,
            min_score=45.0, take_profit=None)

CFGS = [
    dict(),                                        # 基准
    dict(min_score=46),
    dict(min_score=47),
    dict(min_score=48),
    dict(min_score=50),
    dict(hold_days=10),
    dict(hold_days=12),
    dict(hold_days=18),
    dict(top_n=8),
    dict(top_n=12),
    dict(min_score=47, hold_days=12),
    dict(min_score=48, hold_days=12),
    dict(min_score=48, top_n=8),
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
              f"win={m.get('win_rate', 0):.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"md={m.get('max_drawdown', 0):.1f}% "
              f"elapsed={time.time()-t0:.0f}s")
    except Exception as e:
        print(f"[{i}] {json.dumps(extra, ensure_ascii=False)} ERROR: {e}")
