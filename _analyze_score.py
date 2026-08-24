# -*- coding: utf-8 -*-
"""评分制规则搜索：多个特征加权打分，找召回/误报最佳阈值。"""
import json

with open("_mine_limit5_samples.json", "r", encoding="utf-8") as fp:
    data = json.load(fp)
pos = data["pos"]
neg = data["neg"]
print(f"正样本(首板前一日): {len(pos)}  负样本(普通日): {len(neg)}")


def score(x):
    """给样本打分（分数越高越像'连板启动前一日'）。"""
    s = 0.0
    # 涨停基因（核心）
    if x["limit20"] >= 3:
        s += 3
    elif x["limit20"] >= 2:
        s += 2
    elif x["limit20"] >= 1:
        s += 1
    if x["limit60"] >= 12:
        s += 2
    elif x["limit60"] >= 8:
        s += 1
    if x["days_since_limit"] <= 20:
        s += 2
    elif x["days_since_limit"] <= 45:
        s += 1
    # 趋势向上
    if x["close_ma20"] > 0:
        s += 1
    if x["close_ma60"] > 0:
        s += 1
    if x["ma5_ma20"] > 0:
        s += 1
    # 动量强度适中（不追高）
    if 0 <= x["chg20"] <= 25:
        s += 1
    if x["rsi6"] <= 80:
        s += 1
    # 放量
    if x["vol_ratio"] > 1.2:
        s += 1
    return s


print("\n=== 分数分布 ===")
for thr in range(0, 13):
    tp = sum(1 for x in pos if score(x) >= thr)
    fp_ = sum(1 for x in neg if score(x) >= thr)
    rec = tp / len(pos) * 100
    base = fp_ / len(neg) * 100
    if rec < 5:
        continue
    print(f"阈值>= {thr:2d}: 召回 {rec:5.1f}%  误报 {base:5.1f}%  提升 {rec/max(base,0.01):5.1f}x")

# 各特征对正负样本的均值，用于确定最终权重
print("\n=== 特征均值对比 ===")
for f in ("limit20", "limit60", "days_since_limit", "close_ma20", "close_ma60",
          "ma5_ma20", "chg20", "rsi6", "vol_ratio", "turnover", "amplitude",
          "pct_chg", "range20_pos", "dist_high20"):
    pm = sum(x[f] for x in pos) / len(pos)
    nm = sum(x[f] for x in neg) / len(neg)
    print(f"{f:18s} 正 {pm:8.2f}  负 {nm:8.2f}")
