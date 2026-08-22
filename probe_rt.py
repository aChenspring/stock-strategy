# -*- coding: utf-8 -*-
"""临时探针：查看实时行情/分时接口的返回格式（测试后删除）"""
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")

from stock_sdk import get_last_tick, get_ticks, get_price, get_call_auction, warm_default_connection
warm_default_connection()

def dump(name, v):
    print(f"===== {name} =====")
    try:
        if isinstance(v, (list, tuple)):
            print("type=list len=", len(v))
            for it in v[:3]:
                print("  ", json.dumps(it, ensure_ascii=False, default=str)[:400])
        elif isinstance(v, dict):
            print("type=dict keys=", list(v.keys())[:20])
            print(json.dumps(v, ensure_ascii=False, default=str)[:600])
        else:
            print("type=", type(v).__name__, "val=", str(v)[:300])
    except Exception as e:
        print("  dump err:", e)
    print()

try:
    dump("get_last_tick 000001 count=10", get_last_tick("000001", count=10))
except Exception as e:
    print("get_last_tick err:", repr(e))
try:
    dump("get_ticks 000001 count=20", get_ticks("000001", count=20))
except Exception as e:
    print("get_ticks err:", repr(e))
try:
    dump("get_price 000001", get_price("000001"))
except Exception as e:
    print("get_price err:", repr(e))
try:
    dump("get_call_auction 000001", get_call_auction("000001"))
except Exception as e:
    print("get_call_auction err:", repr(e))
