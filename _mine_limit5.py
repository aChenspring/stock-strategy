# -*- coding: utf-8 -*-
"""
策略挖掘：找出历史中「连续涨停≥5日」的股票事件，
提取「首板启动前一日」的特征（正样本），与全市场普通日特征（负样本）对比，
为「连板启动前一日扫描」策略提供特征依据。

注意：所有特征必须只依赖 valid K线行 + _calc_indicators_from_rows 的 calc，
与扫描端/回测端 check_strategy 完全同口径，保证挖掘->策略->扫描/回测三方一致。
"""
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


def is_limit_up(code: str, row: dict) -> bool:
    pct = _f(row.get("pct_chg"))
    if _st(row):
        return pct >= 4.5
    if code.startswith(("30", "68")):
        return pct >= 19.5
    if code.startswith("920"):
        return pct >= 29.5
    return pct >= 9.5


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


# ---------- 特征提取（与 check_strategy 同口径） ----------
FEATURES = [
    "pct_chg",          # 前一日涨幅
    "close_ma20",       # 收盘相对20日线偏离
    "close_ma60",       # 收盘相对60日线偏离
    "bull",             # ma5>ma10>ma20>ma60 多头排列
    "ma5_ma20",         # ma5/ma20 - 1
    "chg20",            # 近20日涨幅
    "chg60",            # 近60日涨幅
    "dist_high20",      # 距20日高点
    "dist_high60",      # 距60日高点
    "vol_ratio",        # 量比
    "turnover",         # 换手率
    "rsi6",
    "macd",
    "amplitude",        # 振幅
    "limit20",          # 近20日涨停次数
    "limit60",          # 近60日涨停次数
    "days_since_limit", # 距上次涨停交易日数
    "range20_pos",      # 20日区间分位
]


def extract(valid_rows, code):
    """从截至某日的有效行提取特征。valid_rows[-1] 为观察日。"""
    calc = _calc_indicators_from_rows(valid_rows)
    last = valid_rows[-1]
    closes = [_f(r.get("close")) or 0 for r in valid_rows]
    highs = [_f(r.get("high")) or 0 for r in valid_rows]
    lows = [_f(r.get("low")) or 0 for r in valid_rows]
    n = len(closes)
    close = closes[-1] or 0.0

    # 近20/60日涨停次数 & 距上次涨停
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

    ma5 = calc.get("ma5") or 0.0
    ma10 = calc.get("ma10") or 0.0
    ma20 = calc.get("ma20") or 0.0
    ma60 = calc.get("ma60") or 0.0
    high20 = calc.get("high20") or max(highs[-20:], default=0) or close
    high60 = calc.get("high60") or max(highs[-60:], default=0) or close
    low20 = min(lows[-20:], default=0) or close
    low60 = calc.get("low60") or min(lows[-60:], default=0) or close

    return {
        "pct_chg": _f(last.get("pct_chg")),
        "close_ma20": (close / ma20 - 1) * 100 if ma20 else 0.0,
        "close_ma60": (close / ma60 - 1) * 100 if ma60 else 0.0,
        "bull": 1.0 if (ma5 and ma10 and ma20 and ma60 and ma5 > ma10 > ma20 > ma60) else 0.0,
        "ma5_ma20": (ma5 / ma20 - 1) * 100 if ma20 else 0.0,
        "chg20": (close / closes[-21] - 1) * 100 if n >= 21 and closes[-21] else 0.0,
        "chg60": (close / closes[-61] - 1) * 100 if n >= 61 and closes[-61] else 0.0,
        "dist_high20": (close / high20 - 1) * 100 if high20 else 0.0,
        "dist_high60": (close / high60 - 1) * 100 if high60 else 0.0,
        "vol_ratio": _f(last.get("vol_ratio")) or (_f(last.get("volume")) / (calc.get("vol_avg5") or 1) if calc.get("vol_avg5") else 0.0),
        "turnover": _f(last.get("turnover")),
        "rsi6": calc.get("rsi6") or 0.0,
        "macd": calc.get("macd") or 0.0,
        "amplitude": _f(last.get("amplitude")),
        "limit20": float(limit20),
        "limit60": float(limit60),
        "days_since_limit": float(days_since_limit),
        "range20_pos": (close - low20) / (high20 - low20) * 100 if high20 > low20 else 50.0,
    }


# ---------- 事件检测 ----------
t1 = time.time()
pos = []      # 正样本：首板前一日
pos_info = []  # (code, date, 首板日, 连板数)
neg = []      # 负样本：随机普通日
n_events = 0

for code, rows in rows_map.items():
    v = valid_trading_rows(rows)
    if len(v) < 70:
        continue
    n = len(v)
    limit_flags = [is_limit_up(code, r) for r in v]

    # 连续涨停段检测
    j = 0
    while j < n:
        if limit_flags[j]:
            k = j
            while k < n and limit_flags[k]:
                k += 1
            streak = k - j
            if streak >= 5 and j >= 65:
                # 事件：首板日 = j，启动前一日 = j-1
                n_events += 1
                pos.append(extract(v[:j], code))
                pos_info.append((code, str(v[j - 1].get("date")), str(v[j].get("date")), streak))
            j = k
        else:
            j += 1

    # 负样本：随机抽 1 个非涨停启动前日（避开事件窗口）
    for _ in range(1):
        idx = random.randint(65, n - 2)
        if not limit_flags[idx]:
            neg.append(extract(v[: idx + 1], code))
            break

print(f"事件检测完成: {n_events} 个连续涨停>=5日事件, {time.time()-t1:.0f}s")
print(f"正样本(首板前一日): {len(pos)}  负样本(普通日): {len(neg)}")

# ---------- 统计对比 ----------
print("\n特征             正样本均值   正样本中位   负样本均值   负样本中位   diff")
for f in FEATURES:
    pv = [x[f] for x in pos]
    nv = [x[f] for x in neg]
    if not pv or not nv:
        continue
    pm, pmed = sum(pv) / len(pv), sorted(pv)[len(pv) // 2]
    nm, nmed = sum(nv) / len(nv), sorted(nv)[len(nv) // 2]
    diff = (pm - nm)
    marker = " <===" if abs(diff) > 3 else ""
    print(f"{f:16s} {pm:10.2f} {pmed:12.2f} {nm:10.2f} {nmed:12.2f} {diff:8.2f}{marker}")

# 保存样本供后续分析
import json
with open("_mine_limit5_samples.json", "w", encoding="utf-8") as fp:
    json.dump({"pos": pos, "neg": neg, "pos_info": pos_info}, fp, ensure_ascii=False)
print("\n样本已保存 _mine_limit5_samples.json")
print("示例事件(前20):")
for c, d0, d1, streak in pos_info[:20]:
    print(f"  {c} 启动前一日={d0} 首板={d1} 连板={streak}")
