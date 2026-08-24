# -*- coding: utf-8 -*-
"""基于已挖掘样本，搜索判别规则组合（正样本召回率 vs 负样本误报率）。"""
import json
import itertools

with open("_mine_limit5_samples.json", "r", encoding="utf-8") as fp:
    data = json.load(fp)
pos = data["pos"]
neg = data["neg"]
print(f"正样本(首板前一日): {len(pos)}  负样本(普通日): {len(neg)}")

# 单特征阈值扫描
def rule_hit(x, cond):
    f, op, v = cond
    val = x.get(f)
    if val is None:
        return False
    if op == ">=":
        return val >= v
    if op == ">":
        return val > v
    if op == "<=":
        return val <= v
    if op == "<":
        return val < v
    if op == "between":
        return v[0] <= val <= v[1]
    return False


# 候选规则（从分布差异看）：每个规则给 (feature, op, value)
CANDIDATES = [
    ("chg60", ">", 5), ("chg60", ">", 10), ("chg60", ">", 15), ("chg60", ">", 20),
    ("chg20", ">", 3), ("chg20", ">", 5), ("chg20", ">", 8), ("chg20", ">", 10),
    ("close_ma20", ">", 0), ("close_ma20", ">", 2), ("close_ma20", ">", 3), ("close_ma20", ">", 5),
    ("close_ma60", ">", 0), ("close_ma60", ">", 5), ("close_ma60", ">", 8), ("close_ma60", ">", 10),
    ("rsi6", ">", 45), ("rsi6", ">", 50), ("rsi6", ">", 55), ("rsi6", "between", (40, 75)),
    ("limit20", ">=", 1), ("limit20", ">=", 2), ("limit20", ">=", 3),
    ("limit60", ">=", 8), ("limit60", ">=", 12), ("limit60", ">=", 15), ("limit60", ">=", 20),
    ("days_since_limit", "<=", 30), ("days_since_limit", "<=", 60), ("days_since_limit", "<=", 90), ("days_since_limit", "<=", 120),
    ("bull", ">=", 1),
    ("turnover", ">", 2), ("turnover", ">", 4),
    ("vol_ratio", ">", 1.0), ("vol_ratio", ">", 1.5),
    ("range20_pos", ">", 45), ("range20_pos", ">", 55),
    ("macd", ">", 0),
    ("pct_chg", "between", (-3, 5)),
    ("amplitude", ">", 3),
    ("dist_high20", ">", -15), ("dist_high20", ">", -10),
    ("ma5_ma20", ">", 0),
]

results = []
for c in CANDIDATES:
    tp = sum(1 for x in pos if rule_hit(x, c))
    fp_ = sum(1 for x in neg if rule_hit(x, c))
    rec = tp / len(pos) * 100
    base = fp_ / len(neg) * 100
    lift = rec / base if base > 0 else 99
    results.append((rec, base, lift, c))

results.sort(key=lambda r: -r[2])
print("\n=== 单规则：召回率%  负样本命中%  提升倍数  规则 ===")
for rec, base, lift, c in results[:35]:
    print(f"{rec:8.1f} {base:10.1f} {lift:8.1f}x  {c}")

# 组合规则搜索：从高判别单规则中选 2-3 个组合
print("\n=== 组合规则（AND）===")
top_singles = [r[3] for r in results[:12]]
combo_results = []
for r in range(2, 4):
    for combo in itertools.combinations(top_singles, r):
        tp = sum(1 for x in pos if all(rule_hit(x, c) for c in combo))
        fp_ = sum(1 for x in neg if all(rule_hit(x, c) for c in combo))
        rec = tp / len(pos) * 100
        base = fp_ / len(neg) * 100
        # 平衡：召回率高 + 误报率低
        score = rec - 3 * base
        combo_results.append((score, rec, base, combo))

combo_results.sort(key=lambda r: -r[0])
print(f"{'score':>6s} {'召回':>7s} {'误报':>7s}  组合")
for score, rec, base, combo in combo_results[:25]:
    print(f"{score:6.1f} {rec:7.1f} {base:7.1f}  {' & '.join(str(c) for c in combo)}")
