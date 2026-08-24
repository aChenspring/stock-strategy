# -*- coding: utf-8 -*-
"""扩展窗口验证：深度超卖在不同回测起点的表现。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None, min_score=48.0, top_n=8,
            market_chg20_max=-12.0, init_cash=100_000)

CFGS = [
    dict(start="20250101"),
    dict(start="20240101"),
    dict(start="20250601"),
]

for i, extra in enumerate(CFGS):
    c = dict(BASE)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        buys = sorted(set(t["buy_date"] for t in res["trades"]))
        print(f"[{i}] start={extra.get('start')}")
        print(f"    total={m.get('total_return', 0):.2f}% "
              f"annual={m.get('annual_return', 0):.2f}% "
              f"trades={len(res['trades'])} "
              f"win={m.get('win_rate', 0):.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"md={m.get('max_drawdown', 0):.1f}% "
              f"elapsed={time.time()-t0:.0f}s")
        print(f"    买入日: {buys}")
    except Exception as e:
        print(f"[{i}] start={extra.get('start')} ERROR: {e}")
