# -*- coding: utf-8 -*-
"""综合全部特征做最终规则搜索 + 时间切分验证。"""
import json
import itertools

with open("_mine_limit5b_samples.json", "r", encoding="utf-8") as fp:
    data = json.load(fp)
pos = data["pos"]
neg = data["neg"]
pos_info = data["pos_info"]
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
    ("ma5_ma20", ">", 0),
    ("chg5", ">", 0), ("chg5", ">", 2),
    ("chg20", ">", 0), ("chg20", ">", 3), ("chg20", ">", 5), ("chg20", ">", 8),
    ("chg60", ">", 0), ("chg60", ">", 5), ("chg60", ">", 10), ("chg60", ">", 15),
    ("rsi6", "between", (40, 80)), ("rsi6", ">", 50),
    ("range20_pos", ">", 40), ("range20_pos", ">", 50),
    ("vol_ratio", ">", 1.0),
    ("turnover", ">", 2), ("turnover", ">", 4),
    ("macd", ">", 0),
    ("float_mv", "<=", 40), ("float_mv", "<=", 60), ("float_mv", "<=", 80), ("float_mv", "<=", 120),
    ("pre_chg", ">", 0), ("pre_chg", ">", 1),
    ("amplitude", ">", 3), ("amplitude", ">", 4),
    ("pct_chg", "between", (-5, 7)),
    ("dist_high20", ">", -20),
]

singles = []
for c in CANDIDATES:
    tp = sum(1 for x in pos if rule_hit(x, c))
    fp_ = sum(1 for x in neg if rule_hit(x, c))
    rec = tp / len(pos) * 100
    base = fp_ / len(neg) * 100
    if rec < 15:
        continue
    singles.append((rec - 6 * base, rec, base, c))
singles.sort(key=lambda r: -r[0])
print("\n=== 单规则 TOP 25 ===")
for sc, rec, base, c in singles[:25]:
    print(f"{sc:7.1f} 召回{rec:6.1f}% 误报{base:5.1f}%  {c}")

top = [s[3] for s in singles[:20]]
results = []
for r in (2, 3):
    for combo in itertools.combinations(top, r):
        tp = sum(1 for x in pos if all(rule_hit(x, c) for c in combo))
        fp_ = sum(1 for x in neg if all(rule_hit(x, c) for c in combo))
        rec = tp / len(pos) * 100
        base = fp_ / len(neg) * 100
        if rec < 20:
            continue
        results.append((rec - 6 * base, rec, base, combo))
results.sort(key=lambda r: -r[0])
print("\n=== 组合规则 TOP 30 ===")
for sc, rec, base, combo in results[:30]:
    print(f"{sc:7.1f} 召回{rec:6.1f}% 误报{base:5.1f}%  {' & '.join(str(c) for c in combo)}")
