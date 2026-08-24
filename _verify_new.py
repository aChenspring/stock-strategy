# -*- coding: utf-8 -*-
"""验证新策略（超卖反弹）在全市场池下的回测收益。"""
import json
import time

from backtest import run_backtest

BASE = dict(
    strategy="factor_default", start="", end="",
    universe="all", max_codes=0, pre_days=60,
)

CFGS = [
    # min_score 挖掘（超卖过滤 + 新规则）
    dict(min_score=44),
    dict(min_score=45),
    dict(min_score=46),
    dict(min_score=48),
    # 45 + init_cash 放大（消除低价股偏差）
    dict(min_score=45, init_cash=100_000),
    dict(min_score=45, init_cash=200_000),
    # 45 + hold 10/20 天
    dict(min_score=45, hold_days=10),
    dict(min_score=45, hold_days=20),
    # 45 + 止盈/止损
    dict(min_score=45, take_profit=12.0),
    dict(min_score=45, stop_loss=-8.0),
    dict(min_score=45, take_profit=12.0, stop_loss=-8.0),
]

for i, extra in enumerate(CFGS):
    c = dict(BASE)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        print(f"[{i}] cfg={json.dumps(extra, ensure_ascii=False)}")
        print(f"    total={m.get('total_return', 0):.2f}% "
              f"annual={m.get('annual_return', 0):.2f}% "
              f"trades={len(res['trades'])} win={m.get('win_rate', 0)*100:.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"days={m.get('days', 0)} elapsed={time.time()-t0:.0f}s")
    except Exception as e:
        print(f"[{i}] cfg={json.dumps(extra, ensure_ascii=False)} ERROR: {e}")
