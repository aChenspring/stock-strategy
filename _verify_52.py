# -*- coding: utf-8 -*-
"""细扫：以 top6/hold10/min45/TP=None/100k 为基准（+52.28%），
在 hold/topN/min_score 邻域扫描，寻找更稳健的 >+50% 组合；
同时验证 6000 元小资金下的表现。
用法：python _verify_52.py [起始] [结束]
"""
import sys
import time

from backtest import run_backtest

BASE = dict(strategy="factor_default", start="20200101", end="",
            universe="all", max_codes=0, pre_days=60,
            market_filter=True, market_filter_mode="oversold",
            market_rsi_threshold=40.0, max_cash_pct=1.0,
            take_profit=None, init_cash=100_000,
            min_score=45.0, top_n=6, hold_days=10,
            market_chg20_max=-14.0, market_chg20_max2=-10.0, market_chg60_min=0.0)

CFGS = [
    ("基准复现(100k/top6/hold10/min45)", dict()),
    ("top5/hold10/min45", dict(top_n=5)),
    ("top7/hold10/min45", dict(top_n=7)),
    ("top6/hold9/min45", dict(hold_days=9)),
    ("top6/hold11/min45", dict(hold_days=11)),
    ("top6/hold10/min44", dict(min_score=44.0)),
    ("top6/hold10/min46", dict(min_score=46.0)),
    ("6000/top6/hold10/min45", dict(init_cash=6000)),
    ("6000/top5/hold10/min45", dict(init_cash=6000, top_n=5)),
    ("6000/top4/hold10/min45", dict(init_cash=6000, top_n=4)),
]

lo = int(sys.argv[1]) if len(sys.argv) > 1 else 0
hi = int(sys.argv[2]) if len(sys.argv) > 2 else len(CFGS)
out = open("_verify_52_out.txt", "a", encoding="utf-8")
for i in range(lo, hi):
    name, extra = CFGS[i]
    c = dict(BASE)
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
