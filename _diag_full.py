# -*- coding: utf-8 -*-
"""诊断：全量池下候选质量分析。
对每个调仓日，dump 通过 judge_at 的候选（含综合分、近5日涨幅、前20日涨幅、
当日量比），并统计其买入后 15 日的收益分布，找因子区分度的改进方向。
"""
import time
from collections import defaultdict

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, judge_at,
)
from screen_common import DEFAULT_SCAN_FILTERS
from strategy_data import A_SHARE_PREFIXES, calc_window_start
from strategy_schema import build_factor_defs, build_rules_map

BASE = dict(
    strategy="factor_default", start="", end="", fee_rate=0.0005,
    init_cash=6000, stop_loss=-12.0, take_profit=20.0,
    rebalance_every=2, universe="all", max_codes=0, pre_days=60,
    market_filter=True, market_filter_mode="strong", ma_up_days=3,
    config=None, top_n=10, hold_days=15, min_score=55.0, max_buy_pct=6.0,
)
c = dict(DEFAULT_BT_CONFIG)
c.update(BASE)

t0 = time.time()
defs_full = build_factor_defs(c.get("config"))
rmap = build_rules_map(c.get("config"))

universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
print(f"universe={len(universe)}", flush=True)

dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 120 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
print(f"rows={len(rows_map)}", flush=True)

series_map = {}
for code, rows in rows_map.items():
    s = IndicatorSeries(code, rows)
    if s.n >= 60:
        series_map[code] = s
print(f"series={len(series_map)}", flush=True)

axis = _market_axis(series_map, c["start"], dates_end)
print(f"axis={len(axis)} days: {axis[0]} ~ {axis[-1]}", flush=True)

# 候选 + 前向收益分析（无买卖模拟，只统计信号质量）
n_cand = 0
n_trade = 0
fwd_stats = []          # (score, fwd15)
score_buckets = defaultdict(list)
code_stats = defaultdict(lambda: {"n": 0, "fwd": []})

max_buy_pct = c.get("max_buy_pct") or None
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                     c["min_score"], defs_full, rmap, True, "factor_default")
        if r is None:
            continue
        n_cand += 1
        sc = r["scored"]["total"]
        i = s.index_at(date)
        px_now = s._data["close"][i]
        # 前向 15 日收益（回看15天窗口的平均）
        j = min(i + 15, s.n - 1)
        fwd = (s._data["close"][j] / px_now - 1) * 100.0 if px_now else 0.0
        fwd_stats.append((sc, fwd))
        code_stats[code]["n"] += 1
        code_stats[code]["fwd"].append(fwd)
        b = int(sc // 10) * 10
        score_buckets[b].append(fwd)

print(f"\n候选总数={n_cand}  前向15日平均={sum(f[1] for f in fwd_stats)/max(1,len(fwd_stats)):.2f}%")

print("\n== 综合分桶 vs 前向15日收益 ==")
for b in sorted(score_buckets):
    fwds = score_buckets[b]
    win = sum(1 for x in fwds if x > 0) / len(fwds) * 100
    print(f"  score {b:3d}-{b+9:3d}: n={len(fwds):4d} avg={sum(fwds)/len(fwds):6.2f}% win={win:5.1f}%")

# 高分候选特征对比：win vs lose
print("\n== 候选（分>=80）当日特征对比 ==")
hi = [f for f in fwd_stats if f[0] >= 80]
if hi:
    win_hi = [x[1] for x in hi if x[1] > 0]
    lose_hi = [x[1] for x in hi if x[1] <= 0]
    print(f"  n={len(hi)} avg={sum(x[1] for x in hi)/len(hi):.2f}% win={len(win_hi)/len(hi)*100:.1f}%")

print(f"\n耗时 {time.time()-t0:.0f}s")
