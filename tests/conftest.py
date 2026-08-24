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
_ss.zb = None
_ss.warm_default_connection = lambda: None
_ss.is_login = lambda: True
sys.modules["stock_sdk"] = _ss

# ---------- mock strategy_data（最小接口） ----------
_sd = types.ModuleType("strategy_data")
_sd.END = "20260821"
_sd.A_SHARE_PREFIXES = ["sh60", "sz00", "sz30"]
_sd._finite = lambda v: v if isinstance(v, (int, float)) and isfinite(v) else None
_sd.valid_trading_rows = lambda rows: rows
_sd.load_market_rows = lambda prefixes, start, end: {}
# factors 顶层会 from strategy_data import compute_board_env / compute_market_env；
# mock 需补齐这两个名字（score_factor_local 的 ctx 摊平不调用它们，仅保证导入成功）
_sd.compute_board_env = lambda rows, info_map=None: {}
_sd.compute_market_env = lambda rows: {}


def _shift_days(date_str, days):
    from datetime import datetime, timedelta
    return (datetime.strptime(date_str, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


def _shift_months(date_str, months):
    from datetime import datetime
    dt = datetime.strptime(date_str, "%Y%m%d")
    year = dt.year
    month = dt.month + months
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    max_day = [31, 29 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 28,
               31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    day = min(dt.day, max_day)
    return f"{year:04d}{month:02d}{day:02d}"


def _calc_window_start(end_date, window):
    if not end_date:
        end_date = _sd.END
    w = str(window).strip().lower()
    if w.endswith("m"):
        return _shift_months(end_date, -int(w[:-1]))
    if w.endswith("y"):
        return _shift_months(end_date, -int(w[:-1]) * 12)
    if w.isdigit():
        return _shift_days(end_date, -int(w) * 2)
    return _shift_months(end_date, -6)


_sd.shift_days = _shift_days
_sd.shift_months = _shift_months
_sd.calc_window_start = _calc_window_start
_sd.calc_backtest_pre_start = lambda end_date, window, pre_days=60: (
    _calc_window_start(end_date, window),
    _shift_days(_calc_window_start(end_date, window), -pre_days * 2),
)
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
