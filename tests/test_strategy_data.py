# -*- coding: utf-8 -*-
"""strategy_data 工具函数测试。"""
import pytest

from strategy_data import shift_days, shift_months, calc_window_start, calc_backtest_pre_start


class TestShiftDays:
    def test_shift_forward_and_back(self):
        assert shift_days("20260822", 1) == "20260823"
        assert shift_days("20260822", -1) == "20260821"
        assert shift_days("20260822", 10) == "20260901"


class TestShiftMonths:
    def test_shift_months_back(self):
        assert shift_months("20260822", -1) == "20260722"
        assert shift_months("20260822", -6) == "20260222"

    def test_shift_months_cross_year(self):
        assert shift_months("20260115", -1) == "20251215"
        assert shift_months("20260131", -1) == "20251231"

    def test_month_end_clamping(self):
        # 2026-08-31 回退 1 个月 -> 2026-07-31
        assert shift_months("20260831", -1) == "20260731"
        # 2026-05-31 回退 1 个月 -> 2026-04-30
        assert shift_months("20260531", -1) == "20260430"


class TestCalcWindowStart:
    def test_scan_window_months(self):
        assert calc_window_start("20260822", "3m") == "20260522"
        assert calc_window_start("20260822", "6m") == "20260222"
        assert calc_window_start("20260822", "1y") == "20250822"

    def test_backtest_window_days(self):
        start = calc_window_start("20260822", "120")
        # 120 个交易日按 1.6 自然日估算 -> 约 192 天前
        assert start < "20260222"

    def test_default_window(self):
        # 非法窗口回退 6 个月
        assert calc_window_start("20260822", "") == "20260222"


class TestCalcBacktestPreStart:
    def test_returns_tuple(self):
        bt_start, pre_start = calc_backtest_pre_start("20260822", "120", pre_days=60)
        assert bt_start < "20260822"
        assert pre_start < bt_start
