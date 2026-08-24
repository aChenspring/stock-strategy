# -*- coding: utf-8 -*-
"""验证：低价股过滤（price_max）在无大盘过滤下是否复现并超越收益。"""
import json
import time

from backtest import run_backtest

FULL = {"boards": {"main": True, "gem": True, "star": True, "bse": True},
        "non_st": True}

BASE = dict(strategy="factor_default", start="", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=False)

CFGS = [
    # 基准：6000 元无价格过滤
    dict(min_score=45),
    # 100k + 不同价格上限
    dict(min_score=45, init_cash=100_000,
         filters=dict(FULL, price_max=8.0)),
    dict(min_score=45, init_cash=100_000,
         filters=dict(FULL, price_max=6.0)),
    dict(min_score=45, init_cash=100_000,
         filters=dict(FULL, price_max=5.0)),
    # 6000 + 价格上限
    dict(min_score=45, filters=dict(FULL, price_max=8.0)),
    # 100k + 上限 + 参数
    dict(min_score=45, init_cash=100_000, hold_days=12,
         filters=dict(FULL, price_max=8.0)),
    dict(min_score=45, init_cash=100_000, take_profit=12.0,
         filters=dict(FULL, price_max=8.0)),
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
