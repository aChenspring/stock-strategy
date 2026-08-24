# -*- coding: utf-8 -*-
"""组合验证：深度超卖家族 × 资金规模 × 阈值。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None)

CFGS = [
    # 基准最优
    dict(init_cash=100_000, market_chg20_max=-12.0, min_score=48.0, top_n=8),
    # 6000 小资金版
    dict(init_cash=6000, market_chg20_max=-12.0, min_score=48.0, top_n=8),
    # -8 阈值（含3月行情）
    dict(init_cash=100_000, market_chg20_max=-8.0, min_score=48.0, top_n=8),
    dict(init_cash=6000, market_chg20_max=-8.0, min_score=48.0, top_n=8),
    # -10 阈值
    dict(init_cash=100_000, market_chg20_max=-10.0, min_score=48.0, top_n=8),
    dict(init_cash=6000, market_chg20_max=-10.0, min_score=48.0, top_n=8),
    # -12 + hold 10（快速反弹）
    dict(init_cash=100_000, market_chg20_max=-12.0, min_score=48.0, top_n=8, hold_days=10),
    dict(init_cash=6000, market_chg20_max=-12.0, min_score=48.0, top_n=8, hold_days=10),
    # -12 小资金 + min_score 47
    dict(init_cash=6000, market_chg20_max=-12.0, min_score=47.0, top_n=8),
    # -12 小资金 + top_n 5
    dict(init_cash=6000, market_chg20_max=-12.0, min_score=48.0, top_n=5),
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
