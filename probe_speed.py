# -*- coding: utf-8 -*-
"""环节耗时探针：逐段计时扫描流程的每个环节，定位瓶颈。"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, r"c:/Users/wxb/CodeBuddy/20250928162354")

from strategy_data import (load_market_rows, compute_indicators,
                           load_stock_boards, compute_board_env,
                           compute_market_env, MarketCache, OnlineData,
                           valid_trading_rows)
from factors import score_stock
from main import PREFIXES, START, END


def ts(name, t0):
    print(f"[{time.time()-t0:7.1f}s] {name}", flush=True)
    return time.time()


t = time.time()
rows_by_code = load_market_rows(PREFIXES, START, END)
t = ts(f"load_market_rows 行情加载 {len(rows_by_code)}只", t)

candidates = {}
for code, rows in rows_by_code.items():
    valid = valid_trading_rows(rows)
    if len(valid) >= 60:
        candidates[code] = valid
print(f"候选池 {len(candidates)}只", flush=True)
t = ts("行情过滤", t)

# 第一次：真实计算（无缓存）
t0 = time.time()
indicators = compute_indicators(candidates)
print(f"指标(首次,含缓存写入) {round(time.time()-t0,1)}s, {len(indicators)}只", flush=True)
# 第二次：缓存命中
t0 = time.time()
indicators2 = compute_indicators(candidates)
print(f"指标(二次,缓存命中) {round(time.time()-t0,1)}s, {len(indicators2)}只", flush=True)
t = ts("指标计算", t)

boards = load_stock_boards(list(candidates.keys()))
t = ts(f"load_stock_boards 板块批量 {len(candidates)}只", t)

env = compute_board_env(candidates, boards)
t = ts("compute_board_env 板块环境", t)

market = compute_market_env(candidates)
t = ts("compute_market_env 市场环境", t)

cache = MarketCache()
online = OnlineData(cache)
online.fundamentals_batch(list(candidates.keys()), batch=100)
t = ts("fundamentals_batch 在线财务批量", t)

# 评分循环（8线程，模拟 run）
t0 = time.time()
def process(code):
    rows = candidates[code]
    valid = valid_trading_rows(rows)
    if not valid:
        return None
    ind = indicators.get(code, {})
    fund = online.fundamentals(code) or {}
    val = online.valuation(code)
    flow = online.money_flow(code, days=5) or {}
    onl = {"fund": fund or {}, "val": val or {}, "flow": flow}
    return score_stock(code, rows, ind, env.get(code, 0), market, onl)

with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(process, list(candidates.keys())))
print(f"评分循环(8线程,纯Python) {round(time.time()-t0,1)}s", flush=True)
t = ts("评分循环", t)

print("探针完成", flush=True)
