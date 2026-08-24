# -*- coding: utf-8 -*-
"""真实数据最终验证：直接调用 check_strategy("v9Limit5")，
统计「连板启动前一日」召回率 vs 全市场普通日误报率，确认与挖掘一致。"""
import json
import random
import time

from strategies import check_strategy
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
                # 启动前一日命中判定：check_strategy 使用 v[:j]（不含首板当日）
                pos.append(check_strategy("v9Limit5", v[:j], {}))
                pos_info.append((code, str(v[j - 1].get("date")), str(v[j].get("date")), streak))
            j = k
        else:
            j += 1
    for _ in range(1):
        idx = random.randint(65, n - 2)
        if not limit_flags[idx]:
            neg.append(check_strategy("v9Limit5", v[: idx + 1], {}))
            break

print(f"事件检测完成: {n_events} 事件, {time.time()-t1:.0f}s")
tp = sum(pos)
rec = tp / len(pos) * 100 if pos else 0
fp_ = sum(neg)
base = fp_ / len(neg) * 100 if neg else 0
print(f"正样本(启动前一日): {len(pos)}  命中 {tp}  召回 {rec:.1f}%")
print(f"负样本(全市场普通日): {len(neg)}  误报 {fp_}  误报率 {base:.1f}%")
print(f"提升倍数: {rec / max(base, 0.01):.1f}x")

# 时间切分
pos_25 = [x for x, info in zip(pos, pos_info) if info[1] < "20260101"]
pos_26 = [x for x, info in zip(pos, pos_info) if info[1] >= "20260101"]
print(f"2025 前一日召回: {sum(pos_25)/len(pos_25)*100:.1f}% ({len(pos_25)})")
print(f"2026 前一日召回: {sum(pos_26)/len(pos_26)*100:.1f}% ({len(pos_26)})")
