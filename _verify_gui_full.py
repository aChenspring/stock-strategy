# -*- coding: utf-8 -*-
"""全量窗口(20200101起)下，最优参数复现 + 页面默认参数组合验证。

目标：确认页面默认参数(6000/top10/min55/hold15)能否在 oversold+深度条件
下达到 +50%；若不能，给出最接近的可用组合。
用法：python _verify_gui_full.py [起始索引] [结束索引]
"""
import sys
import time

from backtest import run_backtest

# 最优基线（_verify_final.py 记录：全量 +48.68%）
BEST = dict(strategy="factor_default", start="20200101", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None, init_cash=100_000,
            min_score=48.0, top_n=8, hold_days=12,
            market_chg20_max=-14.0, market_chg20_max2=-10.0, market_chg60_min=0.0)

CFGS = [
    ("最优基线复现(100k/top8/hold12/min48/TP=None)", dict()),
    ("页面参数+全量(6000/top10/min55/hold15/TP=20)", dict(init_cash=6000, top_n=10,
                                                          min_score=55.0, hold_days=15,
                                                          take_profit=20.0, stop_loss=-12.0)),
    ("页面参数+min48(6000/top10/hold15)", dict(init_cash=6000, top_n=10,
                                               min_score=48.0, hold_days=15,
                                               take_profit=20.0, stop_loss=-12.0)),
    ("页面参数+min48/top8/hold12", dict(init_cash=6000, top_n=8,
                                        min_score=48.0, hold_days=12,
                                        take_profit=20.0, stop_loss=-12.0)),
    ("6000/top8/hold12/min48/TP=None", dict(init_cash=6000, top_n=8,
                                            min_score=48.0, hold_days=12,
                                            take_profit=None)),
    ("6000/top6/hold12/min45/TP=None", dict(init_cash=6000, top_n=6,
                                            min_score=45.0, hold_days=12,
                                            take_profit=None)),
    ("100k/top6/hold12/min45/TP=None", dict(init_cash=100_000, top_n=6,
                                            min_score=45.0, hold_days=12,
                                            take_profit=None)),
    ("100k/top6/hold10/min45/TP=None", dict(init_cash=100_000, top_n=6,
                                            min_score=45.0, hold_days=10,
                                            take_profit=None)),
]

lo = int(sys.argv[1]) if len(sys.argv) > 1 else 0
hi = int(sys.argv[2]) if len(sys.argv) > 2 else len(CFGS)
out = open("_verify_gui_full_out.txt", "a", encoding="utf-8")
for i in range(lo, hi):
    name, extra = CFGS[i]
    c = dict(BEST)
    c.update(extra)
    t0 = time.time()
    try:
        res = run_backtest(c, progress_cb=lambda m, p: None)
        m = res["metrics"]
        buys = sorted(set(t["buy_date"] for t in res["trades"]))
        line = (f"[{i}] {name}\n"
                f"    total={m.get('total_return', 0):.2f}% "
                f"annual={m.get('annual_return', 0):.2f}% "
                f"trades={len(res['trades'])} "
                f"win={m.get('win_rate', 0):.1f}% "
                f"pf={m.get('profit_factor', 0):.2f} "
                f"md={m.get('max_drawdown', 0):.1f}% "
                f"elapsed={time.time()-t0:.0f}s\n"
                f"    买入日: {buys}\n")
    except Exception as e:
        line = f"[{i}] {name} ERROR: {e}\n"
    print(line, end="", flush=True)
    out.write(line)
    out.flush()
out.close()
