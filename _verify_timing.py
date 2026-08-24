# -*- coding: utf-8 -*-
"""验证：oversold 大盘过滤 + 高分选股 在 100k 下的收益。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold")

CFGS = [
    # 默认阈值40 + 基础参数
    dict(min_score=45, init_cash=100_000, market_rsi_threshold=40.0),
    # 阈值35
    dict(min_score=45, init_cash=100_000, market_rsi_threshold=35.0),
    # 阈值30
    dict(min_score=45, init_cash=100_000, market_rsi_threshold=30.0),
    # 阈值45
    dict(min_score=45, init_cash=100_000, market_rsi_threshold=45.0),
    # 40 + hold 20
    dict(min_score=45, init_cash=100_000, market_rsi_threshold=40.0,
         hold_days=20),
    # 40 + hold 25
    dict(min_score=45, init_cash=100_000, market_rsi_threshold=40.0,
         hold_days=25),
    # 40 + min_score 48
    dict(min_score=48, init_cash=100_000, market_rsi_threshold=40.0,
         hold_days=20),
    # 40 + top_n 5 集中
    dict(min_score=45, init_cash=100_000, market_rsi_threshold=40.0,
         hold_days=20, top_n=5),
    # 40 + 6000元小资金
    dict(min_score=45, init_cash=6000, market_rsi_threshold=40.0),
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
