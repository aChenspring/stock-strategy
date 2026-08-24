# -*- coding: utf-8 -*-
"""调试：新规则评分 TOP 候选的特征与前向收益，验证选股区分度。"""
import time

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, judge_at,
)
from screen_common import DEFAULT_SCAN_FILTERS
from strategy_data import A_SHARE_PREFIXES
from strategy_schema import build_factor_defs, build_rules_map

c = dict(DEFAULT_BT_CONFIG)
c.update(max_codes=0, pre_days=60)
defs_full = build_factor_defs(c.get("config"))
rmap = build_rules_map(c.get("config"))

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 120 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
axis = _market_axis(series_map, c["start"], dates_end)
print(f"series={len(series_map)} axis={len(axis)}", flush=True)

max_buy_pct = c.get("max_buy_pct") or None
recs = []
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                     -999.0, defs_full, rmap, True, "factor_default")
        if r is None:
            continue
        sc = r["scored"]["total"]
        i = s.index_at(date)
        d = s._data
        px = d["close"][i]
        j = min(i + 15, s.n - 1)
        fwd = (d["close"][j] / px - 1) * 100.0
        recs.append({
            "code": code, "date": date, "score": sc, "fwd": fwd,
            "chg20": round((px / d["close"][max(0, i-20)] - 1) * 100, 1),
            "pr": round(d["profit_ratio"][i], 2),
            "turn": round(d["turnover"][i] or 0, 2),
            "pct": round(d["pct"][i] or 0, 2),
            "chg5": round((px / d["close"][max(0, i-5)] - 1) * 100, 1),
            "amp": round(d["amplitude"][i] or 0, 1),
            "bull": int(bool(d["bull_arrange"][i])),
            "kd": int(bool(d["kd_strong"][i])),
        })

recs.sort(key=lambda x: -x["score"])
print(f"候选总数={len(recs)} fwd15均值={sum(r['fwd'] for r in recs)/len(recs):.2f}%")
print("\n== TOP 40 候选（按新评分） ==")
print(f"{'date':10s} {'code':8s} {'score':5s} {'fwd15':6s} {'chg20':6s} {'pr':4s} "
      f"{'turn':5s} {'pct':5s} {'chg5':6s} {'amp':5s} {'bull':4s} {'kd':3s}")
for r in recs[:40]:
    print(f"{r['date']:10s} {r['code']:8s} {r['score']:5.1f} {r['fwd']:6.2f} "
          f"{r['chg20']:6.1f} {r['pr']:4.2f} {r['turn']:5.2f} {r['pct']:5.2f} "
          f"{r['chg5']:6.1f} {r['amp']:5.1f} {r['bull']:4d} {r['kd']:3d}")

# 分段统计
print("\n== 分段 fwd15 ==")
for lo, hi in [(45, 60), (40, 45), (35, 40), (30, 35)]:
    arr = [r["fwd"] for r in recs if lo <= r["score"] < hi]
    if arr:
        win = sum(1 for x in arr if x > 0) / len(arr) * 100
        print(f"  score {lo}-{hi}: n={len(arr):6d} avg={sum(arr)/len(arr):6.2f}% win={win:5.1f}%")
print(f"耗时 {time.time()-t0:.0f}s")
