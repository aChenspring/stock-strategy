# -*- coding: utf-8 -*-
"""
网格搜索最优规则 + 命中后收益统计（T日首板买入，看后续收益）。
对每个「启动前一日」抽样特征，搜索能最大化「精确率@召回率」的规则。
"""
import json
import random
import time

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


# 对每只股票，在 j>=65 的每个日子提取特征（正样本=次日启动连板>=5，负样本抽样）
t1 = time.time()
pos_feats = []   # (feat_dict, 首板日收益...)
neg_feats = []
n_events = 0

for code, rows in rows_map.items():
    v = valid_trading_rows(rows)
    if len(v) < 66:
        continue
    n = len(v)
    flags = [is_limit_up(code, r) for r in v]
    # 预计算 j 日特征（仅当需要时）
    feat_cache = {}
    for j in range(65, n - 1):
        # 次日是否开始连板>=5
        is_event = False
        if flags[j + 1]:
            k = j + 1
            while k < n and flags[k]:
                k += 1
            if k - (j + 1) >= 5:
                is_event = True
        if not is_event:
            continue
        n_events += 1
        # 提取 j 日特征
        sub = v[: j + 1]
        last = sub[-1]
        closes = [_f(r.get("close")) or 0 for r in sub]
        c = closes[-1] or 0
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else c
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else c
        limit20 = limit60 = 0
        days_since = -1
        for k in range(j, -1, -1):
            if flags[k]:
                limit60 += 1
                if k >= j - 19:
                    limit20 += 1
                if days_since < 0:
                    days_since = j - k
        if days_since < 0:
            days_since = 999
        # 首板收益（T日买入涨停收益近似 pct_chg）
        first_ret = _f(v[j + 1].get("pct_chg"))
        # 首板后累计收益（5日）
        future = closes[j + 2:] if j + 2 < n else []
        ret5 = (future[-1] / closes[j + 1] - 1) * 100 if len(future) >= 5 and closes[j + 1] else 0
        pos_feats.append({
            "limit20": limit20, "limit60": limit60, "days_since": days_since,
            "close_ma20": (c / ma20 - 1) * 100 if ma20 else 0,
            "close_ma60": (c / ma60 - 1) * 100 if ma60 else 0,
            "pct_chg": _f(last.get("pct_chg")),
            "float_mv": _f(last.get("float_mv")) / 1e8,
            "turnover": _f(last.get("turnover")),
            "ret_first": first_ret, "ret5": ret5,
        })
    # 负样本：每只股票随机抽 8 个非事件普通日
    picked = 0
    while picked < 8:
        j = random.randint(65, n - 2)
        if flags[j + 1]:
            continue
        # 简单看下是否非事件
        sub = v[: j + 1]
        last = sub[-1]
        closes = [_f(r.get("close")) or 0 for r in sub]
        c = closes[-1] or 0
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else c
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else c
        limit20 = limit60 = 0
        days_since = -1
        for k in range(j, -1, -1):
            if flags[k]:
                limit60 += 1
                if k >= j - 19:
                    limit20 += 1
                if days_since < 0:
                    days_since = j - k
        if days_since < 0:
            days_since = 999
        neg_feats.append({
            "limit20": limit20, "limit60": limit60, "days_since": days_since,
            "close_ma20": (c / ma20 - 1) * 100 if ma20 else 0,
            "close_ma60": (c / ma60 - 1) * 100 if ma60 else 0,
            "pct_chg": _f(last.get("pct_chg")),
            "float_mv": _f(last.get("float_mv")) / 1e8,
            "turnover": _f(last.get("turnover")),
            "ret_first": 0, "ret5": 0,
        })
        picked += 1

print(f"特征提取完成: {len(pos_feats)} 正样本(启动前一日), {len(neg_feats)} 负样本, {time.time()-t1:.0f}s")
print(f"总事件数: {n_events}")

# 负样本抽样权重：全市场天数 / 负样本数
total_days = sum(max(0, len(valid_trading_rows(r)) - 66) for r in rows_map.values())
neg_weight = total_days / len(neg_feats) if neg_feats else 1
print(f"负样本权重(近似): {neg_weight:.1f}")


def rule_hit(x, c):
    f, op, v = c
    val = x.get(f)
    if val is None:
        return False
    if op == ">=":
        return val >= v
    if op == ">":
        return val > v
    if op == "<=":
        return val <= v
    if op == "between":
        return v[0] <= val <= v[1]
    return False


# 网格：从强判别特征组合
GRID = [
    ("limit20", ">=", [1, 2, 3]),
    ("limit60", ">=", [5, 8, 10, 15]),
    ("days_since", "<=", [20, 30, 45, 60]),
    ("close_ma20", ">", [0, 2, 5]),
    ("close_ma60", ">", [0, 3]),
    ("float_mv", "<=", [30, 50, 80, 120]),
    ("turnover", ">", [1, 2, 3]),
    ("pct_chg", "between", [(-5, 8)]),
]

results = []
# 2-3 条件组合
import itertools
keys = list(GRID)
best = []
# 用代表性单条件生成候选组合
cands = []
for f, op, vals in GRID:
    for v in vals:
        cands.append((f, op, v))

for r in (2, 3):
    for combo in itertools.combinations(cands, r):
        tp = sum(1 for x in pos_feats if all(rule_hit(x, c) for c in combo))
        if tp < 30:
            continue
        fp_ = sum(1 for x in neg_feats if all(rule_hit(x, c) for c in combo))
        rec = tp / len(pos_feats) * 100
        fp_w = fp_ * neg_weight
        prec = tp / (tp + fp_w) * 100 if (tp + fp_w) else 0
        score = rec - 6 * (fp_w / total_days * 100)
        results.append((score, prec, rec, combo))

results.sort(key=lambda r: -r[0])
print("\n=== 组合规则 TOP 30 (score=召回-6*全市场误报率) ===")
print(f"{'score':>7s} {'精确率':>7s} {'召回':>7s}  组合")
for sc, prec, rec, combo in results[:30]:
    print(f"{sc:7.2f} {prec:6.2f}% {rec:6.1f}%  {' & '.join(str(c) for c in combo)}")
