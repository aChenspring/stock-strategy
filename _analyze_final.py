# -*- coding: utf-8 -*-
"""验证最终硬条件组合规则在样本上的召回/误报。"""
import json

with open("_mine_limit5_samples.json", "r", encoding="utf-8") as fp:
    data = json.load(fp)
pos = data["pos"]
neg = data["neg"]
print(f"正样本(首板前一日): {len(pos)}  负样本(普通日): {len(neg)}")


def strategy_hit(x):
    """v9Limit5 连板启动前一日策略（硬条件 AND）。"""
    # 涨停基因：近20日涨停>=2
    if x["limit20"] < 2:
        return False
    # 近60日涨停>=5（长期活跃）
    if x["limit60"] < 5:
        return False
    # 距上次涨停<=45日（启动动能尚在）
    if x["days_since_limit"] > 45:
        return False
    # 趋势：收盘站上MA20且偏离0~15%
    if not (0 < x["close_ma20"] <= 15):
        return False
    # 中期趋势向上
    if x["close_ma60"] <= 0:
        return False
    # 动量：MACD>0 且 20日涨幅 0~30%
    if x["macd"] <= 0:
        return False
    if not (0 <= x["chg20"] <= 30):
        return False
    # 避免已经是涨停日/追高：当日涨幅<8%
    if x["pct_chg"] >= 8:
        return False
    return True


def strategy_hit_b2(x):
    """宽松版：去掉 MACD/chg20 约束。"""
    if x["limit20"] < 2:
        return False
    if x["days_since_limit"] > 60:
        return False
    if not (0 < x["close_ma20"] <= 20):
        return False
    if x["pct_chg"] >= 8:
        return False
    return True


for name, fn in (("严格版", strategy_hit), ("宽松版", strategy_hit_b2)):
    tp = sum(1 for x in pos if fn(x))
    fp_ = sum(1 for x in neg if fn(x))
    rec = tp / len(pos) * 100
    base = fp_ / len(neg) * 100
    print(f"\n{name}: 召回 {rec:.1f}% ({tp}/{len(pos)})  误报 {base:.1f}% ({fp_}/{len(neg)})  "
          f"提升 {rec / max(base, 0.01):.1f}x")
