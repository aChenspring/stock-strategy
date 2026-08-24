# -*- coding: utf-8 -*-
"""深度超卖 + 分批建仓(max_cash_pct) 组合验证。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, init_cash=100_000)

CFGS = [
    # 深度-8/-10/-12 + max_cash_pct 0.3
    dict(min_score=45, market_chg20_max=-8.0, max_cash_pct=0.3),
    dict(min_score=45, market_chg20_max=-10.0, max_cash_pct=0.3),
    dict(min_score=45, market_chg20_max=-12.0, max_cash_pct=0.3),
    # -10 + 不同部署比例
    dict(min_score=45, market_chg20_max=-10.0, max_cash_pct=0.2),
    dict(min_score=45, market_chg20_max=-10.0, max_cash_pct=0.5),
    # -10 + 0.3 + hold 20 / 25
    dict(min_score=45, market_chg20_max=-10.0, max_cash_pct=0.3, hold_days=20),
    dict(min_score=45, market_chg20_max=-10.0, max_cash_pct=0.3, hold_days=25),
    # -10 + 0.3 + 无止损
    dict(min_score=45, market_chg20_max=-10.0, max_cash_pct=0.3, stop_loss=None),
    # -10 + 0.3 + hold 20 无止损
    dict(min_score=45, market_chg20_max=-10.0, max_cash_pct=0.3,
         hold_days=20, stop_loss=None),
]

for i, extra in enumerate(CFGS):
    c = dict(BASE)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        wr = m.get('win_rate', 0)
        md = m.get('max_drawdown', 0)
        print(f"[{i}] {json.dumps(extra, ensure_ascii=False)}")
        print(f"    total={m.get('total_return', 0):.2f}% "
              f"annual={m.get('annual_return', 0):.2f}% "
              f"trades={len(res['trades'])} "
              f"win={wr:.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"md={md:.1f}% "
              f"elapsed={time.time()-t0:.0f}s")
    except Exception as e:
        print(f"[{i}] {json.dumps(extra, ensure_ascii=False)} ERROR: {e}")
