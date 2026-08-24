# -*- coding: utf-8 -*-
"""
策略挖掘 v2：加入市值/成交额/换手等字段，重新提取样本特征。
样本：连续涨停>=5日事件的「首板启动前一日」 vs 全市场普通日。
"""
import json
import random
import time

from strategies import _calc_indicators_from_rows
from strategy_data import load_market_rows, valid_trading_rows, A_SHARE_PREFIXES, END

random.seed(42)
t0 = time.time()
start = "20240101"
print(f"加载数据 {start} ~ {END} ...")
rows_map = load_market_rows(A_SHARE_PREFIXES, start, END)
print(f"加载完成 {len(rows_map)} 只, {sum(len(v) for v in rows_map.values())} 行, {time.time()-t0:.0f}s")


def _f(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _st(row):
    try:
        return bool(row.get("is_st"))
    except Exception:
        return False


def is_limit_up(code: str, row: dict) -> bool:
    pct = _f(row.get("pct_chg"))
    if _st(row):
        return pct >= 4.5
    if code.startswith(("30", "68")):
        return pct >= 19.5
    if code.startswith("920"):
        return pct >= 29.5
    return pct >= 9.5


def extract(valid_rows, code):
    calc = _calc_indicators_from_rows(valid_rows)
    last = valid_rows[-1]
    closes = [_f(r.get("close")) or 0 for r in valid_rows]
    highs = [_f(r.get("high")) or 0 for r in valid_rows]
    lows = [_f(r.get("low")) or 0 for r in valid_rows]
    n = len(closes)
    close = closes[-1] or 0.0

    limit20 = limit60 = 0
    days_since_limit = -1
    for k in range(n - 1, -1, -1):
        if is_limit_up(code, valid_rows[k]):
            limit60 += 1
            if k >= n - 20:
                limit20 += 1
            if days_since_limit < 0:
                days_since_limit = (n - 1) - k
    if days_since_limit < 0:
        days_since_limit = 999

    ma20 = calc.get("ma20") or 0.0
    ma60 = calc.get("ma60") or 0.0
    high20 = calc.get("high20") or max(highs[-20:], default=0) or close
    high60 = calc.get("high60") or max(highs[-60:], default=0) or close
    low20 = min(lows[-20:], default=0) or close
    low60 = calc.get("low60") or min(lows[-60:], default=0) or close
    vol_avg5 = calc.get("vol_avg5") or 0.0
    vol = _f(last.get("volume"))

    return {
        "pct_chg": _f(last.get("pct_chg")),
        "close_ma20": (close / ma20 - 1) * 100 if ma20 else 0.0,
        "close_ma60": (close / ma60 - 1) * 100 if ma60 else 0.0,
        "bull": 1.0 if all(calc.get(k) for k in ("ma5", "ma10", "ma20", "ma60")) and calc["ma5"] > calc["ma10"] > calc["ma20"] > calc["ma60"] else 0.0,
        "ma5_ma20": (calc.get("ma5") or 0) / ma20 - 1 * 100 if ma20 else 0.0,
        "chg5": (close / closes[-6] - 1) * 100 if n >= 6 and closes[-6] else 0.0,
        "chg20": (close / closes[-21] - 1) * 100 if n >= 21 and closes[-21] else 0.0,
        "chg60": (close / closes[-61] - 1) * 100 if n >= 61 and closes[-61] else 0.0,
        "dist_high20": (close / high20 - 1) * 100 if high20 else 0.0,
        "dist_high60": (close / high60 - 1) * 100 if high60 else 0.0,
        "vol_ratio": _f(last.get("vol_ratio")) or (vol / vol_avg5 if vol_avg5 else 0.0),
        "turnover": _f(last.get("turnover")),
        "rsi6": calc.get("rsi6") or 0.0,
        "macd": calc.get("macd") or 0.0,
        "amplitude": _f(last.get("amplitude")),
        "limit20": float(limit20),
        "limit60": float(limit60),
        "days_since_limit": float(days_since_limit),
        "range20_pos": (close - low20) / (high20 - low20) * 100 if high20 > low20 else 50.0,
        "amount": _f(last.get("amount")) / 1e8,          # 亿元
        "float_mv": _f(last.get("float_mv")) / 1e8,      # 亿元
        "pre_chg": _f(valid_rows[-2].get("pct_chg")) if n >= 2 else 0.0,
    }


t1 = time.time()
pos = []
pos_info = []
neg = []
n_events = 0

for code, rows in rows_map.items():
    v = valid_trading_rows(rows)
    if len(v) < 70:
        continue
    n = len(v)
    limit_flags = [is_limit_up(code, r) for r in v]
    j = 0
    while j < n:
        if limit_flags[j]:
            k = j
            while k < n and limit_flags[k]:
                k += 1
            streak = k - j
            if streak >= 5 and j >= 65:
                n_events += 1
                pos.append(extract(v[:j], code))
                pos_info.append((code, str(v[j - 1].get("date")), str(v[j].get("date")), streak))
            j = k
        else:
            j += 1
    for _ in range(1):
        idx = random.randint(65, n - 2)
        if not limit_flags[idx]:
            neg.append(extract(v[: idx + 1], code))
            break

print(f"事件检测完成: {n_events} 事件, {time.time()-t1:.0f}s")
print(f"正样本: {len(pos)}  负样本: {len(neg)}")

FEATURES = ["pct_chg", "close_ma20", "close_ma60", "bull", "chg5", "chg20", "chg60",
            "dist_high20", "dist_high60", "vol_ratio", "turnover", "rsi6", "macd",
            "amplitude", "limit20", "limit60", "days_since_limit", "range20_pos",
            "amount", "float_mv", "pre_chg"]
print("\n特征             正均值   正中位   负均值   负中位   diff")
for f in FEATURES:
    pv = [x[f] for x in pos]
    nv = [x[f] for x in neg]
    pm, pmed = sum(pv) / len(pv), sorted(pv)[len(pv) // 2]
    nm, nmed = sum(nv) / len(nv), sorted(nv)[len(nv) // 2]
    print(f"{f:16s} {pm:8.2f} {pmed:8.2f} {nm:8.2f} {nmed:8.2f} {pm - nm:8.2f}")

with open("_mine_limit5b_samples.json", "w", encoding="utf-8") as fp:
    json.dump({"pos": pos, "neg": neg, "pos_info": pos_info}, fp, ensure_ascii=False)
print("\n已保存 _mine_limit5b_samples.json")
