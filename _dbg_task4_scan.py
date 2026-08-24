# -*- coding: utf-8 -*-
"""扫描 min_score 阈值 → 候选命中数，定位 0 命中的临界点。

口径：oversold+深度条件(RSI14<40, chg20=-14, chg20b=-10, chg60=0)，
全市场抽样 400 只，20200101 起全部 oversold 深度买入日。
"""
import time

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    IndicatorSeries, judge_at, _market_ok, _sma,
)
from screen_common import DEFAULT_SCAN_FILTERS
from strategy_data import A_SHARE_PREFIXES
from strategy_schema import build_factor_defs, build_rules_map

CFG = dict(
    strategy="factor_default", start="20200101", end="", universe="all",
    max_codes=400, pre_days=60, market_filter=True,
    market_filter_mode="oversold", market_rsi_threshold=40.0,
    market_chg20_max=-14.0, market_chg20_max2=-10.0, market_chg60_min=0.0,
    max_buy_pct=6.0, filters=DEFAULT_SCAN_FILTERS,
)

t0 = time.time()
c = CFG

universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
dates_end = c["end"] or _latest_end()
pre_start = _default_start(c["start"], c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
print(f"load/series: {len(series_map)} codes, {time.time()-t0:.0f}s", flush=True)

axis = _market_axis(series_map, c["start"], dates_end)
market_close: list = []
last_mc = None
for date in axis:
    cs = [s._data["close"][s.index_at(date)] for s in series_map.values()
          if s.index_at(date) >= 0]
    v = sum(cs) / len(cs) if cs else last_mc
    last_mc = v
    market_close.append(v)
market_ma20 = _sma([v if v is not None else 0.0 for v in market_close], 20)

defs_full = build_factor_defs(c.get("config"))
rmap = build_rules_map(c.get("config"))
print(f"prepared, {time.time()-t0:.0f}s", flush=True)

# 收集所有 oversold 深度买入日的候选分数
buy_days = []
day_scores_all = []
for di, date in enumerate(axis):
    if di % 2 != 0:
        continue
    ok = _market_ok(market_close, market_ma20, di, True, "oversold", 3,
                    40.0, -14.0, -10.0, 0.0)
    if not ok:
        continue
    buy_days.append(date)
    ds = []
    for code, s in series_map.items():
        if not s.has_date(date):
            continue
        r = judge_at(s, date, c["filters"], True, c["max_buy_pct"],
                     0.0, defs_full, rmap, True, "factor_default")
        if r is not None:
            ds.append(r["scored"]["total"])
    day_scores_all.append((date, ds))

all_scores = sorted(sc for _, ds in day_scores_all for sc in ds)
print(f"oversold深度买入日: {len(buy_days)}, 总候选: {len(all_scores)}, "
      f"{time.time()-t0:.0f}s", flush=True)

# 扫描 min_score 阈值
print("\n=== min_score 阈值扫描（候选命中数）===", flush=True)
print(f"{'min_score':>9} {'候选命中':>8} {'每日平均':>8} "
      f"{'最高分':>6}  {'买入日命中数'}", flush=True)
prev_n = -1
first_zero = None
last_nonzero = None
for ms in range(0, 61):
    n = sum(1 for sc in all_scores if sc >= ms)
    days_hit = sum(1 for _, ds in day_scores_all if any(sc >= ms for sc in ds))
    avg = n / len(buy_days) if buy_days else 0
    mx = max(all_scores, default=0.0)
    if n == 0 and prev_n > 0:
        first_zero = ms
    if n > 0:
        last_nonzero = ms
    prev_n = n
    mark = ""
    if n == 0 and first_zero == ms:
        mark = "  ← 首个0命中"
    if n > 0 and ms == last_nonzero:
        mark = "  ← 最后非0"
    print(f"{ms:>9} {n:>8} {avg:>8.2f} {mx:>6.1f}  {days_hit:>4}{mark}", flush=True)

print(f"\n临界结论: min_score≤{last_nonzero} 有候选, "
      f"min_score≥{first_zero} 为 0 命中", flush=True)
print(f"elapsed={time.time()-t0:.0f}s", flush=True)
