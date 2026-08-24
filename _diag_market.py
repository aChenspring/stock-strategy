# -*- coding: utf-8 -*-
"""验证大盘过滤日的市场环境 + 组合特征前向收益。"""
import time
from collections import defaultdict

from backtest import (
    _sampled_universe, _load_rows, _market_axis, _default_start, _latest_end,
    DEFAULT_BT_CONFIG, IndicatorSeries, _market_ok,
)
from strategy_data import A_SHARE_PREFIXES

c = dict(DEFAULT_BT_CONFIG)
c.update(max_codes=0, pre_days=60, market_filter=True, market_filter_mode="strong",
         ma_up_days=3)

t0 = time.time()
universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
dates_end = c["end"] or _latest_end()
pre_start = _default_start(dates_end, 120 + c["pre_days"])
rows_map = _load_rows(universe, pre_start, dates_end)
series_map = {code: IndicatorSeries(code, rows)
              for code, rows in rows_map.items() if len(rows) >= 60}
axis = _market_axis(series_map, c["start"], dates_end)

# 市场等权指数 + MA20（与回测一致）
idx = []
for date in axis:
    cs = [s._data["close"][s.index_at(date)] for s in series_map.values()
          if s.has_date(date)]
    idx.append(sum(cs) / len(cs) if cs else None)
ma20 = []
s = 0.0
cnt = 0.0
for i, v in enumerate(idx):
    if v is None:
        ma20.append(None)
        continue
    s += v; cnt += 1
    if i >= 20 and idx[i - 20] is not None:
        s -= idx[i - 20]; cnt -= 1
    ma20.append(s / cnt if cnt else None)

ok_days = []
for di, date in enumerate(axis):
    ok = _market_ok(idx, ma20, di, c["market_filter"], c["market_filter_mode"],
                    c["ma_up_days"])
    ok_days.append(ok)
n_ok = sum(ok_days)
print(f"axis={len(axis)} 大盘过滤通过日={n_ok} ({n_ok/len(axis)*100:.1f}%) "
      f"区间 {axis[0]}~{axis[-1]}", flush=True)

# 每个调仓日：大盘是否OK + 当日所有合格股票的前向15日收益
fwd_ok, fwd_no = [], []
per_day = defaultdict(lambda: {"ok": None, "fwd": []})
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    ok = ok_days[di]
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
        if (d["pct"][i] or 0.0) > 6.0:
            continue
        j = min(i + 15, s.n - 1)
        fwd = (d["close"][j] / px - 1) * 100.0
        per_day[date]["ok"] = ok
        per_day[date]["fwd"].append(fwd)

all_ok = [x for pd in per_day.values() if pd["ok"] for x in pd["fwd"]]
all_no = [x for pd in per_day.values() if not pd["ok"] for x in pd["fwd"]]
for nm, arr in (("OK日", all_ok), ("非OK日", all_no)):
    win = sum(1 for x in arr if x > 0) / len(arr) * 100
    print(f"  {nm}: n={len(arr):7d} avg={sum(arr)/len(arr):6.2f}% win={win:5.1f}%")

# 组合特征：仅在 OK 日
print("\n== OK日 组合特征 fwd15 ==")
combo = {
    "chg20<-10 & pct2-6": lambda r: r["chg20"] < -10 and 2 <= r["pct"] < 6,
    "chg20<-10 & pct0-6 & turn<5": lambda r: r["chg20"] < -10 and 0 <= r["pct"] < 6 and r["turnover"] < 5,
    "pr<0.3 & pct2-6": lambda r: r["profit_ratio"] < 0.3 and 2 <= r["pct"] < 6,
    "chg20<-10 & pr<0.3 & pct2-6": lambda r: r["chg20"] < -10 and r["profit_ratio"] < 0.3 and 2 <= r["pct"] < 6,
    "chg20<-10 & chg5>0 & pct2-6": lambda r: r["chg20"] < -10 and r["chg5"] > 0 and 2 <= r["pct"] < 6,
    "chg20<-15 & turn<5": lambda r: r["chg20"] < -15 and r["turnover"] < 5,
    "not bull & chg20<-10 & pct>0": lambda r: not r["bull"] and r["chg20"] < -10 and r["pct"] > 0,
}
recs = []
for di, date in enumerate(axis):
    if di % c["rebalance_every"] != 0:
        continue
    if not ok_days[di]:
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
        j = min(i + 15, s.n - 1)
        recs.append({
            "fwd": (d["close"][j] / px - 1) * 100.0,
            "pct": pct,
            "turnover": d["turnover"][i] or 0.0,
            "chg5": (px / d["close"][max(0, i - 5)] - 1) * 100 if i >= 5 else 0.0,
            "chg20": (px / d["close"][max(0, i - 20)] - 1) * 100 if i >= 20 else 0.0,
            "profit_ratio": d["profit_ratio"][i],
            "bull": bool(d["bull_arrange"][i]),
        })
print(f"OK日合格样本={len(recs)} avg={sum(r['fwd'] for r in recs)/len(recs):.2f}%")
for nm, fn in combo.items():
    arr = [r["fwd"] for r in recs if fn(r)]
    if arr:
        win = sum(1 for x in arr if x > 0) / len(arr) * 100
        print(f"  {nm:38s} n={len(arr):6d} avg={sum(arr)/len(arr):6.2f}% win={win:5.1f}%")

print(f"\n耗时 {time.time()-t0:.0f}s")
