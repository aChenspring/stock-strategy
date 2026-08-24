# -*- coding: utf-8 -*-
"""模拟 GUI 默认配置（backtest_page._read_cfg 输出）在 oversold+深度条件下的表现。

GUI 默认：6000/top10/min55/hold15/stop-12/profit20/rebal2/抽样400，
大盘过滤=oversold + 深度主条件(-14) + 次条件(-10, chg60>0)。
对比：默认 120 日窗口（start 留空）与全量窗口（20200101）。
"""
import time

from backtest import run_backtest

# 与 backtest_page._read_cfg() 的页面默认输出一致
GUI_BASE = dict(strategy="factor_default", start="", end="", window="",
                pre_days=60, init_cash=6000, top_n=10, hold_days=15,
                fee_rate=0.0005, min_score=55.0, stop_loss=-12.0,
                take_profit=20.0, rebalance_every=2,
                universe="all", max_codes=400,
                market_filter=True, market_filter_mode="oversold",
                ma_up_days=3, market_chg20_max=-14.0,
                market_chg20_max2=-10.0, market_chg60_min=0.0,
                max_buy_pct=6.0, hits_codes=[],
                config=None)

CFGS = [
    ("GUI默认(120日窗口,抽样400,oversold+深度)", dict()),
    ("GUI默认+全量窗口20200101(抽样400)", dict(start="20200101")),
    ("GUI默认+全量窗口(抽样400, hold10)", dict(start="20200101", hold_days=10)),
    ("GUI默认+全量窗口(抽样400, hold12)", dict(start="20200101", hold_days=12)),
]

for i, (name, extra) in enumerate(CFGS):
    c = dict(GUI_BASE)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        buys = sorted(set(t["buy_date"] for t in res["trades"]))
        print(f"[{i}] {name}")
        print(f"    total={m.get('total_return', 0):.2f}% "
              f"annual={m.get('annual_return', 0):.2f}% "
              f"trades={len(res['trades'])} "
              f"win={m.get('win_rate', 0):.1f}% "
              f"pf={m.get('profit_factor', 0):.2f} "
              f"md={m.get('max_drawdown', 0):.1f}% "
              f"elapsed={time.time()-t0:.0f}s")
        print(f"    买入日: {buys}")
    except Exception as e:
        print(f"[{i}] {name} ERROR: {e}")
