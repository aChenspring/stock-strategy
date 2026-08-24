# -*- coding: utf-8 -*-
"""全市场参数对比：大盘过滤模式 × min_score × hold × cash。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60)

CFGS = [
    # ---- 无大盘过滤（纯高分选股）----
    dict(market_filter=False, min_score=45),
    dict(market_filter=False, min_score=45, init_cash=100_000),
    dict(market_filter=False, min_score=45, init_cash=100_000, hold_days=10),
    dict(market_filter=False, min_score=45, init_cash=100_000, hold_days=20),
    dict(market_filter=False, min_score=48, init_cash=100_000),
    dict(market_filter=False, min_score=42, init_cash=100_000),
    dict(market_filter=False, min_score=45, init_cash=100_000, take_profit=12.0),
    # ---- 超卖过滤（阈值放宽到45/50）----
    dict(market_filter_mode="oversold", market_rsi_threshold=45.0,
         min_score=45, init_cash=100_000),
    dict(market_filter_mode="oversold", market_rsi_threshold=50.0,
         min_score=45, init_cash=100_000),
    dict(market_filter_mode="oversold", market_rsi_threshold=50.0,
         min_score=48, init_cash=100_000),
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
