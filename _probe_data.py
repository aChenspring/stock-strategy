# -*- coding: utf-8 -*-
"""快速探测：行情行字段 + 数据规模 + 连续涨停事件数。"""
import time

from strategy_data import load_market_rows, valid_trading_rows, A_SHARE_PREFIXES, END
from strategy_data import calc_window_start

t0 = time.time()
start = "20240101"
rows_map = load_market_rows(A_SHARE_PREFIXES, start, END)
print(f"load {len(rows_map)} codes, {sum(len(v) for v in rows_map.values())} rows, {time.time()-t0:.0f}s")

# 打印一行的字段
sample_code = next(iter(rows_map))
sample_row = valid_trading_rows(rows_map[sample_code])[0]
print(f"sample {sample_code}: keys={sorted(sample_row.keys())}")
print(sample_row)


def is_limit_up(code, row):
    pct = row.get("pct_chg")
    try:
        pct = float(pct)
    except Exception:
        return False
    if code.startswith(("30", "68")):
        return pct >= 19.5
    if code.startswith("920"):
        return pct >= 29.5
    return pct >= 9.5


# 统计连续涨停>=5的事件
events = 0
n_limit_5 = 0
for code, rows in rows_map.items():
    v = valid_trading_rows(rows)
    streak = 0
    first = None
    for r in v:
        if is_limit_up(code, r):
            if streak == 0:
                first = r.get("date")
            streak += 1
            if streak == 5:
                events += 1
                n_limit_5 += 1
        else:
            streak = 0
    if streak >= 5:
        pass
print(f"连续涨停>=5日事件数: {events}")
