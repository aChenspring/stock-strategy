# -*- coding: utf-8 -*-
"""最终规则确认：v2平衡 + 市值约束。"""
import json

with open("_mine_limit5b_samples.json", "r", encoding="utf-8") as fp:
    data = json.load(fp)
pos = data["pos"]
neg = data["neg"]
pos_info = data["pos_info"]
print(f"正样本: {len(pos)}  负样本: {len(neg)}")


def strategy_hit(x, cap=None):
    if x["limit20"] < 2:
        return False
    if x["limit60"] < 8:
        return False
    if x["days_since_limit"] > 45:
        return False
    if not (0 < x["close_ma20"] <= 25):
        return False
    if x["close_ma60"] <= -5:
        return False
    if x["pct_chg"] >= 8:
        return False
    if cap is not None and x["float_mv"] > cap:
        return False
    return True


for cap in (None, 200, 100, 60):
    tp = sum(1 for x in pos if strategy_hit(x, cap))
    fp_ = sum(1 for x in neg if strategy_hit(x, cap))
    rec = tp / len(pos) * 100
    base = fp_ / len(neg) * 100
    print(f"市值<= {str(cap):>5s}: 召回 {rec:5.1f}%  误报 {base:5.1f}%  提升 {rec/max(base,0.01):5.1f}x")

# 最终规则 + 时间切分
tp = sum(1 for x in pos if strategy_hit(x, 200))
fp_ = sum(1 for x in neg if strategy_hit(x, 200))
rec = tp / len(pos) * 100
base = fp_ / len(neg) * 100
print(f"\n最终规则(市值<=200亿): 召回 {rec:.1f}% ({tp}/{len(pos)})  误报 {base:.1f}% ({fp_}/{len(neg)})")
pos_25 = [x for x, info in zip(pos, pos_info) if info[1] < "20260101"]
pos_26 = [x for x, info in zip(pos, pos_info) if info[1] >= "20260101"]
tp_25 = sum(1 for x in pos_25 if strategy_hit(x, 200))
tp_26 = sum(1 for x in pos_26 if strategy_hit(x, 200))
print(f"2025召回: {tp_25/len(pos_25)*100:.1f}%  2026召回: {tp_26/len(pos_26)*100:.1f}%")
