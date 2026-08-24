# -*- coding: utf-8 -*-
"""诊断：GUI 默认参数（min55/maxbuy6/profit20/stop-12/抽样400）下 0 交易的原因。"""
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="20200101", end="", window="",
            pre_days=60, init_cash=6000, top_n=10, hold_days=15,
            fee_rate=0.0005, stop_loss=-12.0, take_profit=20.0,
            rebalance_every=2, universe="all", max_codes=400,
            market_filter=True, market_filter_mode="oversold",
            ma_up_days=3, market_chg20_max=-14.0,
            market_chg20_max2=-10.0, market_chg60_min=0.0,
            hits_codes=[], config=None)

CFGS = [
    ("GUI默认(min55/maxbuy6)", dict(min_score=55.0, max_buy_pct=6.0)),
    ("关max_buy_pct", dict(min_score=55.0, max_buy_pct=None)),
    ("min_score=48 + 关maxbuy", dict(min_score=48.0, max_buy_pct=None)),
    ("min_score=48 + 关maxbuy + take_profit=None", dict(min_score=48.0, max_buy_pct=None, take_profit=None)),
    ("min_score=48 + 关maxbuy + top8/hold12", dict(min_score=48.0, max_buy_pct=None, top_n=8, hold_days=12)),
]

for i, (name, extra) in enumerate(CFGS):
    c = dict(BASE)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        buys = sorted(set(t["buy_date"] for t in res["trades"]))
        print(f"[{i}] {name}")
        print(f"    total={m.get('total_return', 0):.2f}% "
              f"trades={len(res['trades'])} "
              f"win={m.get('win_rate', 0):.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"elapsed={time.time()-t0:.0f}s")
        print(f"    买入日: {buys}")
    except Exception as e:
        print(f"[{i}] {name} ERROR: {e}")
