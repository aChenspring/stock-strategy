# -*- coding: utf-8 -*-
"""回测页 UI 默认值与配置收集测试（offscreen，不弹窗）。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    inst = QApplication.instance()
    return inst if inst is not None else QApplication([])


def test_defaults(app):
    from backtest_page import BacktestPage
    page = BacktestPage()
    try:
        # 建议参数已作为默认值（6000 元小资金场景）
        assert page.ed_cash.text() == "6000"
        assert page.ed_hold.text() == "15"
        assert page.ed_stop.text() == "-12"
        assert page.ed_profit.text() == "20"
        assert page.ed_rebal.text() == "2"
        assert page.ed_topn.text() == "10"
        assert page.ed_minscore.text() == "55"
        assert page.chk_market.isChecked()
        assert page.ed_maxbuy.text() == "6"
        assert page.cb_market_mode.currentData() == "oversold"
        assert page.ed_mkt_chg20.text() == "-14"
        assert page.ed_mkt_chg20b.text() == "-10"
        assert page.ed_mkt_chg60.text() == "0"
    finally:
        page.deleteLater()


def test_read_cfg_contains_new_fields(app):
    from backtest_page import BacktestPage
    page = BacktestPage()
    try:
        cfg = page._read_cfg()
        assert cfg["market_filter"] is True
        assert cfg["market_filter_mode"] == "oversold"
        assert cfg["market_chg20_max"] == -14.0
        assert cfg["market_chg20_max2"] == -10.0
        assert cfg["market_chg60_min"] == 0.0
        assert cfg["max_buy_pct"] == 6.0
        assert cfg["stop_loss"] == -12.0
        assert cfg["take_profit"] == 20.0
        assert cfg["rebalance_every"] == 2
        assert cfg["init_cash"] == 6000
        assert cfg["top_n"] == 10
        assert cfg["hold_days"] == 15
    finally:
        page.deleteLater()


def test_read_cfg_max_buy_empty_means_no_limit(app):
    from backtest_page import BacktestPage
    page = BacktestPage()
    try:
        page.ed_maxbuy.setText("")
        assert page._read_cfg()["max_buy_pct"] is None
        page.ed_maxbuy.setText("0")
        assert page._read_cfg()["max_buy_pct"] is None
        page.ed_maxbuy.setText("10")
        assert page._read_cfg()["max_buy_pct"] == 10.0
    finally:
        page.deleteLater()


def test_read_cfg_full_universe_sets_max_codes_zero(app):
    """全A（全量）选项：max_codes 置 0 触发不抽样全量回测。"""
    from backtest_page import BacktestPage
    page = BacktestPage()
    try:
        page.cb_universe.setCurrentIndex(1)   # 全A（全量）
        assert page.cb_universe.currentData() == "all_full"
        cfg = page._read_cfg()
        assert cfg["universe"] == "all_full"
        assert cfg["max_codes"] == 0
        # 切回抽样后恢复数值
        page.cb_universe.setCurrentIndex(0)   # 全A（抽样）
        assert page._read_cfg()["max_codes"] == 400
    finally:
        page.deleteLater()


def test_defaults_include_time_fields(app):
    """回测页默认展示时间条件相关控件。"""
    from backtest_page import BacktestPage
    page = BacktestPage()
    try:
        assert page.cb_window.currentData() == ""
        assert page.ed_pre_days.text() == "60"
        # 自定义模式下起始日期可编辑
        assert page.ed_start.isEnabled()
    finally:
        page.deleteLater()


def test_read_cfg_time_fields(app):
    """_read_cfg 正确收集窗口长度与预热天数。"""
    from backtest_page import BacktestPage
    page = BacktestPage()
    try:
        cfg = page._read_cfg()
        assert cfg["window"] == ""
        assert cfg["pre_days"] == 60

        page.cb_window.setCurrentIndex(
            page.cb_window.findData("120"))
        page.ed_pre_days.setText("90")
        cfg = page._read_cfg()
        assert cfg["window"] == "120"
        assert cfg["pre_days"] == 90
    finally:
        page.deleteLater()


def test_window_changed_auto_fills_start(app):
    """选择区间长度后，起始日期根据结束日期自动推算并锁定。"""
    from backtest_page import BacktestPage
    page = BacktestPage()
    try:
        page.ed_end.setText("20260822")
        page.cb_window.setCurrentIndex(
            page.cb_window.findData("120"))
        assert page.ed_start.text() != ""
        assert not page.ed_start.isEnabled()
    finally:
        page.deleteLater()
