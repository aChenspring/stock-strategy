# -*- coding: utf-8 -*-
"""每个调仓日：RSI、候选数、全体fwd20、top10 by score fwd20。"""
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

market_close = []
last_mc = None
for date in axis:
    cs = [s._data["close"][s.index_at(date)] for s in series_map.values()
          if s.index_at(date) >= 0]
    v = sum(cs) / len(cs) if cs else last_mc
    last_mc = v
    market_close.append(v)

max_buy_pct = c.get("max_buy_pct") or None
print(f"{'date':10s} {'RSI':5s} {'候选':5s} {'全体f20':8s} {'top10f20':8s}")
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    rsi = _market_rsi(market_close, 14, di)
    recs = []
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
        j = min(i + 20, s.n - 1)
        f20 = (s._data["close"][j] / px - 1) * 100.0
        recs.append((r["scored"]["total"], f20))
    if not recs:
        continue
    all_f = [f for _, f in recs]
    recs.sort(key=lambda x: -x[0])
    top_f = [f for _, f in recs[:10]]
    rsi_s = f"{rsi:.0f}" if rsi is not None else "-"
    print(f"{date:10s} {rsi_s:5s} {len(recs):5d} "
          f"{sum(all_f)/len(all_f):8.2f} {sum(top_f)/len(top_f):8.2f}")
print(f"耗时 {time.time()-t0:.0f}s")
