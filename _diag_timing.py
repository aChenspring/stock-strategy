# -*- coding: utf-8 -*-
"""市场状态 vs 全市场前向收益：寻找正期望的入场窗口。
对每个交易日计算市场指数技术状态，统计全市场股票 fwd15 均值。
"""
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

# 市场等权指数
idx = []
for date in axis:
    cs = [s._data["close"][s.index_at(date)] for s in series_map.values()
          if s.has_date(date)]
    idx.append(sum(cs) / len(cs) if cs else None)

def ma(vals, w):
    out = [None] * len(vals)
    s = 0.0; cnt = 0.0
    for i, v in enumerate(vals):
        if v is None:
            continue
        s += v; cnt += 1
        if i >= w and vals[i - w] is not None:
            s -= vals[i - w]; cnt -= 1
        out[i] = s / cnt if cnt else None
    return out

ma5, ma10, ma20 = ma(idx, 5), ma(idx, 10), ma(idx, 20)
ma60 = ma(idx, 60)
# 指数 RSI14
def rsi(vals, p=14):
    out = [None] * len(vals)
    gains = [0.0] * len(vals); losses = [0.0] * len(vals)
    for i in range(1, len(vals)):
        ch = (vals[i] or 0) - (vals[i - 1] or 0)
        if ch > 0: gains[i] = ch
        else: losses[i] = -ch
    for i in range(p, len(vals)):
        ag = sum(gains[i - p + 1:i + 1]) / p
        al = sum(losses[i - p + 1:i + 1]) / p
        out[i] = 100 - 100 / (1 + (ag / al if al else 1e9))
    return out

idx_rsi = rsi(idx)

# 每个交易日全市场 fwd15（等权）
day_fwd = []
for di, date in enumerate(axis):
    fwd = []
    for s in series_map.values():
        if not s.has_date(date):
            continue
        i = s.index_at(date)
        if i < 60:
            continue
        d = s._data
        px = d["close"][i]
        if not px or px <= 0:
            continue
        j = min(i + 15, s.n - 1)
        fwd.append((d["close"][j] / px - 1) * 100.0)
    day_fwd.append(sum(fwd) / len(fwd) if fwd else None)

def stat(name, arr):
    arr = [x for x in arr if x is not None]
    if not arr:
        return
    win = sum(1 for x in arr if x > 0) / len(arr) * 100
    print(f"  {name:32s} n={len(arr):4d} avg={sum(arr)/len(arr):7.2f}% win={win:5.1f}%")

print("== 市场状态 vs 全市场 fwd15 ==")
# 指数相对MA20
stat("index > MA20", [f for f, i in zip(day_fwd, range(len(idx))) if idx[i] and ma20[i] and idx[i] > ma20[i]])
stat("index < MA20", [f for f, i in zip(day_fwd, range(len(idx))) if idx[i] and ma20[i] and idx[i] <= ma20[i]])
# MA20 斜率
slope_up = [f for f, i in zip(day_fwd, range(len(idx))) if ma20[i] and ma20[max(0, i - 3)] and ma20[i] > ma20[max(0, i - 3)]]
slope_dn = [f for f, i in zip(day_fwd, range(len(idx))) if ma20[i] and ma20[max(0, i - 3)] and ma20[i] <= ma20[max(0, i - 3)]]
stat("MA20 上行", slope_up)
stat("MA20 下行/走平", slope_dn)
# strong 模式（当前过滤器）
strong = [f for f, i in zip(day_fwd, range(len(idx))) if idx[i] and ma20[i] and idx[i] > ma20[i] and ma20[i] > ma20[max(0, i - 3)]]
stat("strong(>MA20且MA20升)", strong)
# 指数RSI
for lo, hi, nm in [(0, 30, "RSI<30"), (30, 40, "RSI 30-40"), (40, 50, "RSI 40-50"),
                   (50, 60, "RSI 50-60"), (60, 70, "RSI 60-70"), (70, 101, "RSI>70")]:
    stat(nm, [f for f, i in zip(day_fwd, range(len(idx)))
              if idx_rsi[i] is not None and lo <= idx_rsi[i] < hi])
# 指数当日涨跌
for lo, hi, nm in [(-99, -2, "指数日跌>2%"), (-2, 0, "指数日跌0-2%"),
                   (0, 1, "指数日涨0-1%"), (1, 2, "指数日涨1-2%"), (2, 99, "指数日涨>2%")]:
    chg = [((idx[i] or 0) / (idx[i - 1] or 1) - 1) * 100 if i and idx[i] and idx[i - 1] else None
           for i in range(len(idx))]
    stat(nm, [f for f, i in zip(day_fwd, range(len(idx))) if chg[i] is not None and lo <= chg[i] < hi])
# 指数距MA20偏离
for lo, hi, nm in [(-99, -5, "dev<-5%"), (-5, -2, "dev -5~-2%"), (-2, 0, "dev -2~0%"),
                   (0, 2, "dev 0~2%"), (2, 5, "dev 2~5%"), (5, 99, "dev>5%")]:
    dev = [((idx[i] or 0) / (ma20[i] or 1) - 1) * 100 if idx[i] and ma20[i] else None
           for i in range(len(idx))]
    stat(nm, [f for f, i in zip(day_fwd, range(len(idx))) if dev[i] is not None and lo <= dev[i] < hi])

print(f"\n耗时 {time.time()-t0:.0f}s")
