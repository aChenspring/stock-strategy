# -*- coding: utf-8 -*-
"""验证：移除止损/止盈截断 + 延长持有期对均值回归策略的影响。"""
import json
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=False)

CFGS = [
    # 100k 基准（带默认止损止盈）
    dict(min_score=45, init_cash=100_000),
    # 去掉止损
    dict(min_score=45, init_cash=100_000, stop_loss=None),
    # 去掉止损 + 去掉止盈
    dict(min_score=45, init_cash=100_000, stop_loss=None, take_profit=None),
    # 去掉止损 + hold 20
    dict(min_score=45, init_cash=100_000, stop_loss=None, hold_days=20),
    # 去掉止损/止盈 + hold 20
    dict(min_score=45, init_cash=100_000, stop_loss=None, take_profit=None,
         hold_days=20),
    # 宽松止损 -25
    dict(min_score=45, init_cash=100_000, stop_loss=-25.0, hold_days=20),
    # 去掉截断 + hold 20 + min_score 48
    dict(min_score=48, init_cash=100_000, stop_loss=None, take_profit=None,
         hold_days=20),
    # 去掉截断 + hold 20 + 高价股偏好（price_min=8）
    dict(min_score=45, init_cash=100_000, stop_loss=None, take_profit=None,
         hold_days=20, filters={"boards": {"main": True, "gem": True,
                                           "star": True, "bse": True},
                                "non_st": True, "price_min": 8.0}),
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
