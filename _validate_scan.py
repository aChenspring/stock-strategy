# -*- coding: utf-8 -*-
"""
全历史模拟扫描验证：对每个交易日全市场应用策略（在 T-1 日判定），
统计「次日启动连续涨停>=5日」的精确率/召回率。
这是对"启动涨停前一日准确扫描"的最直接检验。
"""
import json
import time
from collections import defaultdict

from strategy_data import load_market_rows, valid_trading_rows, A_SHARE_PREFIXES, END

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


def strategy_hit(valid_rows, code):
    """v9Limit5 连板启动前一日：在 T-1 日判定，预测 T 日起连续涨停。
    全部特征只依赖 valid K线行（与回测/扫描 check_strategy 输入一致）。"""
    if len(valid_rows) < 65:
        return False
    last = valid_rows[-1]
    if _st(last):
        return False
    # 当日非涨停日（若当日已涨停，启动已开始）
    if is_limit_up(code, last):
        return False
    # 涨停基因：近20日涨停次数 / 近60日涨停次数 / 距上次涨停
    n = len(valid_rows)
    limit20 = limit60 = 0
    days_since = -1
    for k in range(n - 1, -1, -1):
        if is_limit_up(code, valid_rows[k]):
            limit60 += 1
            if k >= n - 20:
                limit20 += 1
            if days_since < 0:
                days_since = (n - 1) - k
    if days_since < 0:
        days_since = 999
    if limit20 < 2:
        return False
    if limit60 < 10:
        return False
    if days_since > 30:
        return False
    # 趋势：收盘>MA20（用行内均值近似，与策略 calc 一致用简单均线）
    closes = [_f(r.get("close")) or 0 for r in valid_rows]
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else closes[-1]
    if closes[-1] <= ma20:
        return False
    return True


# 预计算每只股票的涨停标记
print("预计算涨停标记...")
limit_map = {}
for code, rows in rows_map.items():
    v = valid_trading_rows(rows)
    limit_map[code] = [is_limit_up(code, r) for r in v]

# 对每个可扫描日（j >= 65 且 j <= n-2，保证有次日），统计
tp = 0   # 命中且次日启动连续涨停>=5
fp = 0   # 命中但未启动
events_total = 0   # 全部"启动连续涨停>=5"事件数
events_hit = 0     # 事件中被提前一日命中的

t1 = time.time()
for code, rows in rows_map.items():
    v = valid_trading_rows(rows)
    if len(v) < 66:
        continue
    n = len(v)
    flags = limit_map[code]
    for j in range(65, n - 1):  # j 为 T-1 日索引
        # 检测是否命中
        hit = strategy_hit(v[: j + 1], code)
        if hit:
            # 看 T 日是否开始连续涨停>=5
            if flags[j + 1]:
                k = j + 1
                while k < n and flags[k]:
                    k += 1
                if k - (j + 1) >= 5:
                    tp += 1
                else:
                    fp += 1
            else:
                fp += 1
        # 检测该位置是否是一个事件的"首板前一日"（用于召回率）
        if flags[j + 1]:
            k = j + 1
            while k < n and flags[k]:
                k += 1
            if k - (j + 1) >= 5:
                events_total += 1
                if hit:
                    events_hit += 1

print(f"扫描完成 {time.time()-t1:.0f}s")
print(f"\n=== v9Limit5 连板启动前一日策略（全历史模拟）===")
print(f"扫描命中数: {tp + fp}")
print(f"其中次日启动连续涨停>=5: {tp}  (未启动: {fp})")
print(f"精确率 (命中后真实启动): {tp / (tp + fp) * 100:.1f}%")
print(f"全部启动事件: {events_total}  被提前一日命中: {events_hit}")
print(f"召回率 (启动事件被扫到): {events_hit / events_total * 100:.1f}%")
