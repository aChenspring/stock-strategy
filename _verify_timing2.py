# -*- coding: utf-8 -*-
"""oversold 过滤 + 移除止损/止盈的收益验证。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, init_cash=100_000)

CFGS = [
    # 无止损（默认止盈20 hold15）
    dict(min_score=45, stop_loss=None),
    # 无止损无止盈
    dict(min_score=45, stop_loss=None, take_profit=None),
    # 无止损 hold 20
    dict(min_score=45, stop_loss=None, hold_days=20),
    # 无止损 hold 25
    dict(min_score=45, stop_loss=None, hold_days=25),
    # 无止损 hold 20 无止盈
    dict(min_score=45, stop_loss=None, take_profit=None, hold_days=20),
    # 宽松止损 -25
    dict(min_score=45, stop_loss=-25.0, hold_days=20),
    # 无止损 hold 20 + 阈值35
    dict(min_score=45, stop_loss=None, hold_days=20, market_rsi_threshold=35.0),
    # 无止损 hold 20 + 阈值45
    dict(min_score=45, stop_loss=None, hold_days=20, market_rsi_threshold=45.0),
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
