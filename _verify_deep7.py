# -*- coding: utf-8 -*-
"""短持有+止损管理，尝试同时捕捉3月/6月/7月。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None, init_cash=100_000)

CFGS = [
    # -8 阈值 + 短持有10 + 宽松止损
    dict(market_chg20_max=-8.0, min_score=45.0, top_n=8, hold_days=10, stop_loss=-8.0),
    dict(market_chg20_max=-8.0, min_score=45.0, top_n=8, hold_days=10, stop_loss=-10.0),
    dict(market_chg20_max=-10.0, min_score=45.0, top_n=8, hold_days=10, stop_loss=-8.0),
    dict(market_chg20_max=-10.0, min_score=45.0, top_n=8, hold_days=10, stop_loss=-10.0),
    # -8 + 止损 + 止盈15
    dict(market_chg20_max=-8.0, min_score=45.0, top_n=8, hold_days=10, stop_loss=-8.0, take_profit=15.0),
    # -12 + 短持有 + 止损（7月快速反弹）
    dict(market_chg20_max=-12.0, min_score=45.0, top_n=8, hold_days=10, stop_loss=-10.0),
    # -8 + min_score 47 + 短持有
    dict(market_chg20_max=-8.0, min_score=47.0, top_n=8, hold_days=10, stop_loss=-10.0),
    # -8 + hold 12
    dict(market_chg20_max=-8.0, min_score=45.0, top_n=8, hold_days=12, stop_loss=-10.0),
    # -12 + hold 15 基准对照
    dict(market_chg20_max=-12.0, min_score=48.0, top_n=8),
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
