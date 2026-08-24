# -*- coding: utf-8 -*-
"""验证最终策略规则 + 时间切分验证（2025前样本训练/2026后样本验证）。"""
import json

with open("_mine_limit5_samples.json", "r", encoding="utf-8") as fp:
    data = json.load(fp)
pos = data["pos"]
neg = data["neg"]
pos_info = data["pos_info"]


def strategy_hit(x):
    """v9Limit5 连板启动前一日策略（硬条件 AND）：
    目标：在启动涨停的前一日命中。"""
    # 涨停基因：近20日涨停>=3（近期至少3次涨停）
    if x["limit20"] < 3:
        return False
    # 长期活跃：近60日涨停>=10
    if x["limit60"] < 10:
        return False
    # 距上次涨停<=30日
    if x["days_since_limit"] > 30:
        return False
    # 趋势：站上MA20且偏离0~20%
    if not (0 < x["close_ma20"] <= 20):
        return False
    # 中期趋势向上
    if x["close_ma60"] <= 0:
        return False
    # 当日非涨停日（若当日涨停则启动已开始，不算前一日）
    if x["pct_chg"] >= 8:
        return False
    # 动量
    if x["macd"] <= 0:
        return False
    return True


def strategy_hit_v2(x):
    """宽松版2：核心=涨停基因+趋势，去掉 MACD。"""
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
    return True


for name, fn in (("v1(严格)", strategy_hit), ("v2(平衡)", strategy_hit_v2)):
    tp = sum(1 for x in pos if fn(x))
    fp_ = sum(1 for x in neg if fn(x))
    rec = tp / len(pos) * 100
    base = fp_ / len(neg) * 100
    print(f"\n{name}: 召回 {rec:.1f}% ({tp}/{len(pos)})  误报 {base:.1f}% ({fp_}/{len(neg)})  "
          f"提升 {rec / max(base, 0.01):.1f}x")

    # 时间切分：2025 训练、2026 验证
    pos_25 = [x for x, info in zip(pos, pos_info) if info[1] < "20260101"]
    pos_26 = [x for x, info in zip(pos, pos_info) if info[1] >= "20260101"]
    tp_25 = sum(1 for x in pos_25 if fn(x))
    tp_26 = sum(1 for x in pos_26 if fn(x))
    print(f"  [切分] 2025召回: {tp_25/len(pos_25)*100:.1f}% ({tp_25}/{len(pos_25)})  "
          f"2026召回: {tp_26/len(pos_26)*100:.1f}% ({tp_26}/{len(pos_26)})")
