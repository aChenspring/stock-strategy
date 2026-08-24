# -*- coding: utf-8 -*-
"""按大盘RSI分桶：score>=45 候选的 fwd15/fwd20，验证超卖择时。"""
import time
from collections import defaultdict

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, judge_at, _market_rsi,
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

# 大盘 close/RSI
market_close = []
last_mc = None
for date in axis:
    cs = [s._data["close"][s.index_at(date)] for s in series_map.values()
          if s.index_at(date) >= 0]
    v = sum(cs) / len(cs) if cs else last_mc
    last_mc = v
    market_close.append(v)

max_buy_pct = c.get("max_buy_pct") or None
buckets = defaultdict(lambda: {"f15": [], "f20": [], "days": set()})
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    rsi = _market_rsi(market_close, 14, di)
    if rsi is None:
        continue
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        r = judge_at(s, date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                     45.0, defs_full, rmap, True, "factor_default")
        if r is None:
            continue
        i = s.index_at(date)
        px = s._data["close"][i]
        if not px:
            continue
        f15 = (s._data["close"][min(i+15, s.n-1)] / px - 1) * 100
        f20 = (s._data["close"][min(i+20, s.n-1)] / px - 1) * 100
        if rsi < 30:
            b = "RSI<30"
        elif rsi < 40:
            b = "30-40"
        elif rsi < 45:
            b = "40-45"
        elif rsi < 50:
            b = "45-50"
        elif rsi < 60:
            b = "50-60"
        else:
            b = ">=60"
        buckets[b]["f15"].append(f15)
        buckets[b]["f20"].append(f20)
        buckets[b]["days"].add(date)

print(f"{'RSI桶':8s} {'天数':5s} {'标的':6s} {'fwd15':8s} {'win15':6s} {'fwd20':8s} {'win20':6s}")
for b in ["RSI<30", "30-40", "40-45", "45-50", "50-60", ">=60"]:
    d = buckets[b]
    if not d["f15"]:
        continue
    a15 = sum(d["f15"]) / len(d["f15"])
    a20 = sum(d["f20"]) / len(d["f20"])
    w15 = sum(1 for x in d["f15"] if x > 0) / len(d["f15"]) * 100
    w20 = sum(1 for x in d["f20"] if x > 0) / len(d["f20"]) * 100
    print(f"{b:8s} {len(d['days']):5d} {len(d['f15']):6d} {a15:8.2f} "
          f"{w15:6.1f} {a20:8.2f} {w20:6.1f}")
print(f"耗时 {time.time()-t0:.0f}s")
