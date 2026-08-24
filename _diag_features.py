# -*- coding: utf-8 -*-
"""特征级区分度分析：统计各特征分组的前向15日收益。"""
import time
from collections import defaultdict

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries,
)
from strategy_data import A_SHARE_PREFIXES

c = dict(DEFAULT_BT_CONFIG)
c.update(max_codes=0, pre_days=60)

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 120 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
axis = _market_axis(series_map, c["start"], dates_end)
print(f"series={len(series_map)} axis={len(axis)} {axis[0]}~{axis[-1]}", flush=True)

recs = []
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        i = s.index_at(date)
        if i < 60:
            continue
        last = s.rows[i]
        if "ST" in str(last.get("name", "")):
            continue
        d = s._data
        px = d["close"][i]
        if not px or px <= 0:
            continue
        pct = d["pct"][i] or 0.0
        if pct > 6.0:
            continue
        j = min(i + 15, s.n - 1)
        fwd = (d["close"][j] / px - 1) * 100.0
        recs.append({
            "fwd": fwd, "pct": pct, "px": px,
            "turnover": d["turnover"][i] or 0.0,
            "vol_ratio": d["vol_ratio"][i],
            "rsi6": d["rsi6"][i] or 0.0,
            "chg5": (px / d["close"][max(0, i - 5)] - 1) * 100 if i >= 5 else 0.0,
            "chg20": (px / d["close"][max(0, i - 20)] - 1) * 100 if i >= 20 else 0.0,
            "break20": bool(d["is_break"][i]),
            "bull": bool(d["bull_arrange"][i]),
            "kd_strong": bool(d["kd_strong"][i]),
            "kd_weak": bool(d["kd_weak"][i]),
            "profit_ratio": d["profit_ratio"][i],
            "amount": d["amount"][i] or 0.0,
        })

print(f"样本={len(recs)} 全样本fwd15均值={sum(r['fwd'] for r in recs)/len(recs):.2f}%")

def bucket(key, bins, labels):
    g = defaultdict(list)
    for r in recs:
        v = r[key]
        for k, (lo, hi) in zip(labels, bins):
            if lo <= v < hi:
                g[k].append(r["fwd"])
                break
    print(f"\n== {key} ==")
    for k in labels:
        fwds = g[k]
        if not fwds:
            continue
        win = sum(1 for x in fwds if x > 0) / len(fwds) * 100
        print(f"  {k:8s} n={len(fwds):6d} avg={sum(fwds)/len(fwds):6.2f}% win={win:5.1f}%")

bucket("px", [(0, 5), (5, 10), (10, 20), (20, 50), (50, 1e9)],
       ["<5", "5-10", "10-20", "20-50", ">50"])
bucket("pct", [(-20, 0), (0, 2), (2, 4), (4, 6.001)],
       ["<0", "0-2", "2-4", "4-6"])
bucket("turnover", [(0, 2), (2, 5), (5, 10), (10, 20), (20, 1e9)],
       ["<2", "2-5", "5-10", "10-20", ">20"])
bucket("chg5", [(-99, -5), (-5, 0), (0, 5), (5, 10), (10, 15), (15, 1e9)],
       ["<-5", "-5~0", "0~5", "5~10", "10~15", ">15"])
bucket("chg20", [(-99, -10), (-10, 0), (0, 10), (10, 20), (20, 30), (30, 1e9)],
       ["<-10", "-10~0", "0~10", "10~20", "20~30", ">30"])
bucket("vol_ratio", [(0, 0.8), (0.8, 1.2), (1.2, 2), (2, 3), (3, 1e9)],
       ["<0.8", "0.8-1.2", "1.2-2", "2-3", ">3"])
bucket("profit_ratio", [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)],
       ["<0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", ">0.8"])
for key in ("break20", "bull", "kd_strong", "kd_weak"):
    print(f"\n== {key} ==")
    for b in (True, False):
        fwds = [r["fwd"] for r in recs if r[key] == b]
        if fwds:
            win = sum(1 for x in fwds if x > 0) / len(fwds) * 100
            print(f"  {str(b):5s} n={len(fwds):6d} avg={sum(fwds)/len(fwds):6.2f}% win={win:5.1f}%")

print(f"\n耗时 {time.time()-t0:.0f}s")
