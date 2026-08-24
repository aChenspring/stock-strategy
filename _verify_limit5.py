# -*- coding: utf-8 -*-
"""验证 v9Limit5 策略：构造连板启动前一日形态，确认命中；构造无涨停基因形态，确认不命中。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategies import check_strategy, _calc_indicators_from_rows, _is_limit_up_row
from tests.conftest import closes_to_rows, trading_dates

def make_closes(limit_days, n=100, base=10.0, daily=0.004):
    """构造收盘价序列：limit_days 为涨停日索引集合，其余日温和上涨。"""
    closes = []
    px = base
    for j in range(n):
        if j in limit_days:
            px *= 1.10
        else:
            px *= (1 + daily)
        closes.append(round(px, 2))
    return closes

# 正样本：近60日10次涨停，近20日3次，距上次涨停7日，趋势向上
limit_days = {52, 56, 60, 64, 68, 72, 76, 82, 87, 92}
closes = make_closes(limit_days)
rows = closes_to_rows(closes, code="600000", name="测试")
calc = _calc_indicators_from_rows(rows)
dev20 = (calc["close"] / calc["ma20"] - 1) * 100
dev60 = (calc["close"] / calc["ma60"] - 1) * 100
print("正样本 close_ma20=%.2f close_ma60=%.2f pct=%.2f" % (
    dev20, dev60, rows[-1]["pct_chg"]))
limit20 = sum(1 for r in rows[-20:] if _is_limit_up_row(r, "600000"))
limit60 = sum(1 for r in rows[-60:] if _is_limit_up_row(r, "600000"))
print("正样本 limit20=%d limit60=%d" % (limit20, limit60))
print("正样本 check_strategy:", check_strategy("v9Limit5", rows, {}))

# 负样本1：无涨停基因（纯温和上涨）
rows2 = closes_to_rows(make_closes(set()), code="600000", name="测试")
print("负样本1 check_strategy:", check_strategy("v9Limit5", rows2, {}))

# 负样本2：涨停基因足够但当日已涨停（启动当日，非前一日）
limit_days3 = {52, 56, 60, 64, 68, 72, 76, 82, 87, 92, 99}
closes3 = make_closes(limit_days3)
rows3 = closes_to_rows(closes3, code="600000", name="测试")
print("负样本2(当日涨停) check_strategy:", check_strategy("v9Limit5", rows3, {}))

# 负样本3：涨停基因足够但收盘在MA20下方（破位）
limit_days4 = {10, 20, 30, 40, 50, 60, 70}
closes4 = make_closes(limit_days4, daily=-0.008)
rows4 = closes_to_rows(closes4, code="600000", name="测试")
calc4 = _calc_indicators_from_rows(rows4)
print("负样本3 close_ma20=%.2f" % ((calc4["close"] / calc4["ma20"] - 1) * 100))
print("负样本3 check_strategy:", check_strategy("v9Limit5", rows4, {}))

# ST 不命中
rows5 = closes_to_rows(closes, code="600000", name="ST测试")
print("ST样本 check_strategy:", check_strategy("v9Limit5", rows5, {}))
