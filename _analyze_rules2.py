# -*- coding: utf-8 -*-
"""更精细的规则搜索：最大化 召回 - k*误报，同时保证召回下限。"""
import json
import itertools

with open("_mine_limit5_samples.json", "r", encoding="utf-8") as fp:
    data = json.load(fp)
pos = data["pos"]
neg = data["neg"]
print(f"正样本: {len(pos)}  负样本: {len(neg)}")


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


CANDIDATES = [
    ("limit20", ">=", 1), ("limit20", ">=", 2), ("limit20", ">=", 3),
    ("limit60", ">=", 5), ("limit60", ">=", 8), ("limit60", ">=", 10), ("limit60", ">=", 12),
    ("days_since_limit", "<=", 20), ("days_since_limit", "<=", 30), ("days_since_limit", "<=", 45),
    ("close_ma20", ">", 0), ("close_ma20", ">", 2), ("close_ma20", ">", 3),
    ("close_ma60", ">", 0), ("close_ma60", ">", 3), ("close_ma60", ">", 5), ("close_ma60", ">", 8),
    ("bull", ">=", 1),
    ("ma5_ma20", ">", 0), ("ma5_ma20", ">", 2),
    ("chg20", ">", 0), ("chg20", ">", 3), ("chg20", ">", 5), ("chg20", ">", 8),
    ("chg60", ">", 0), ("chg60", ">", 5), ("chg60", ">", 10), ("chg60", ">", 15), ("chg60", ">", 20),
    ("rsi6", "between", (40, 80)), ("rsi6", ">", 50), ("rsi6", ">", 55),
    ("range20_pos", ">", 40), ("range20_pos", ">", 50), ("range20_pos", ">", 60),
    ("vol_ratio", ">", 1.0), ("vol_ratio", ">", 1.3),
    ("turnover", ">", 2), ("turnover", ">", 4), ("turnover", ">", 6),
    ("macd", ">", 0),
    ("pct_chg", "between", (-5, 7)), ("pct_chg", "between", (-3, 5)),
    ("amplitude", ">", 3), ("amplitude", ">", 5),
    ("dist_high20", ">", -20), ("dist_high20", ">", -15),
    ("dist_high60", ">", -25),
]

# 单个候选规则评估
singles = []
for c in CANDIDATES:
    tp = sum(1 for x in pos if rule_hit(x, c))
    fp_ = sum(1 for x in neg if rule_hit(x, c))
    rec = tp / len(pos) * 100
    base = fp_ / len(neg) * 100
    singles.append((rec, base, c))
singles.sort(key=lambda r: -(r[0] - 6 * r[1]))
print("\n=== 单规则（score = 召回 - 6*误报）===")
print(f"{'score':>7s} {'召回':>7s} {'误报':>7s}  规则")
for rec, base, c in singles[:20]:
    print(f"{rec - 6 * base:7.1f} {rec:7.1f} {base:7.1f}  {c}")

# 组合搜索：从 top 25 单规则中选 2-4 组合
top_singles = [s[2] for s in singles[:25]]
results = []
for r in (2, 3):
    for combo in itertools.combinations(top_singles, r):
        tp = sum(1 for x in pos if all(rule_hit(x, c) for c in combo))
        fp_ = sum(1 for x in neg if all(rule_hit(x, c) for c in combo))
        rec = tp / len(pos) * 100
        base = fp_ / len(neg) * 100
        if rec < 20:
            continue
        score = rec - 6 * base
        results.append((score, rec, base, combo))

results.sort(key=lambda r: -r[0])
print("\n=== 组合规则 TOP 30（score = 召回 - 6*误报, 召回>=20%）===")
print(f"{'score':>7s} {'召回':>7s} {'误报':>7s}  组合")
for score, rec, base, combo in results[:30]:
    print(f"{score:7.1f} {rec:7.1f} {base:7.1f}  {' & '.join(str(c) for c in combo)}")
