# -*- coding: utf-8 -*-
"""验证：深度超卖（RSI<40 + 大盘chg20<-阈值）组合。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, init_cash=100_000)

CFGS = [
    # 不同深度阈值
    dict(min_score=45, market_chg20_max=-8.0),
    dict(min_score=45, market_chg20_max=-10.0),
    dict(min_score=45, market_chg20_max=-12.0),
    dict(min_score=45, market_chg20_max=-15.0),
    # 深度-10 + 移除止损
    dict(min_score=45, market_chg20_max=-10.0, stop_loss=None),
    dict(min_score=45, market_chg20_max=-12.0, stop_loss=None),
    # 深度-12 + hold 20/25
    dict(min_score=45, market_chg20_max=-12.0, hold_days=20),
    dict(min_score=45, market_chg20_max=-12.0, hold_days=25),
    # 深度-12 + 无止损 + hold 20
    dict(min_score=45, market_chg20_max=-12.0, stop_loss=None, hold_days=20),
    # 深度-12 + 无止损 + hold 20 + min_score 48
    dict(min_score=48, market_chg20_max=-12.0, stop_loss=None, hold_days=20),
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
