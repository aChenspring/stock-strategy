# -*- coding: utf-8 -*-
"""
测试公共配置：屏蔽外部数据源，保证单测可离线、稳定、快速运行。

1. 屏蔽 stock_sdk：真实 stockdb.pyd 是 shiboken 生成的 C 扩展，会与
   PySide6 的 shibokensupport 签名检查冲突（wrapper loop）。
2. 屏蔽 strategy_data 的数据查询部分，由测试提供模拟 K 线工厂。
"""
import sys
import types
from math import isfinite

# ---------- 屏蔽外部 stock_sdk ----------
_ss = types.ModuleType("stock_sdk")
_ss.rd = None
_ss.bk = None
_ss.warm_default_connection = lambda: None
_ss.is_login = lambda: True
sys.modules["stock_sdk"] = _ss

# ---------- mock strategy_data（最小接口） ----------
_sd = types.ModuleType("strategy_data")
_sd.END = "20260821"
_sd.A_SHARE_PREFIXES = ["sh60", "sz00", "sz30"]
_sd._finite = lambda v: isinstance(v, (int, float)) and isfinite(v)
_sd.valid_trading_rows = lambda rows: rows
_sd.load_market_rows = lambda prefixes, start, end: {}
sys.modules["strategy_data"] = _sd


# ---------- 模拟 K 线数据工厂 ----------
def trading_dates(n, start="20260101"):
    """生成 n 个递增工作日，格式 YYYYMMDD。"""
    from datetime import datetime, timedelta
    d = datetime.strptime(start, "%Y%m%d")
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def closes_to_rows(closes, code="000001", name="测试", dates=None):
    """由收盘价序列构造 IndicatorSeries 所需的 K 线 rows。"""
    if dates is None:
        dates = trading_dates(len(closes))
    rows = []
    for j, px in enumerate(closes):
        pct = 0.0 if j == 0 else (closes[j] / closes[j - 1] - 1) * 100
        rows.append({
            "date": dates[j], "code": code, "name": name,
            "open": px, "high": px * 1.01, "low": px * 0.99,
            "close": px, "pct_chg": pct,
            "volume": 1_000_000, "amount": px * 1_000_000,
            "turnover": 5.0, "amplitude": 2.0,
        })
    return rows


def market_data(codes_to_closes):
    """{code: closes} -> {code: rows}，日期统一从 20260101 起。"""
    dates = trading_dates(max(len(v) for v in codes_to_closes.values()))
    return {c: closes_to_rows(v, code=c, name=f"测试{c}", dates=dates)
            for c, v in codes_to_closes.items()}
