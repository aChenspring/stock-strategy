# -*- coding: utf-8 -*-
"""验证：score>=45 + 高价超跌(px>=12) 组合 + 不同退出参数。"""
import json
import time

from backtest import run_backtest

FULL = {"boards": {"main": True, "gem": True, "star": True, "bse": True},
        "non_st": True}

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=False, init_cash=100_000,
            filters=dict(FULL, price_min=12.0))

CFGS = [
    dict(min_score=45, hold_days=20, stop_loss=-15.0, take_profit=30.0),
    dict(min_score=45, hold_days=20, stop_loss=-12.0, take_profit=20.0),
    dict(min_score=45, hold_days=15, stop_loss=-12.0, take_profit=20.0),
    dict(min_score=45, hold_days=25, stop_loss=-15.0, take_profit=30.0),
    dict(min_score=48, hold_days=20, stop_loss=-15.0, take_profit=30.0),
    dict(min_score=45, hold_days=20, stop_loss=-18.0, take_profit=None),
    # 对比：px>=8
    dict(min_score=45, hold_days=20, stop_loss=-15.0, take_profit=30.0,
         filters=dict(FULL, price_min=8.0)),
    # 对比：无价格限制
    dict(min_score=45, hold_days=20, stop_loss=-15.0, take_profit=30.0,
         filters=dict(FULL)),
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
