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
    finally:
        page.deleteLater()


def test_read_cfg_contains_new_fields(app):
    from backtest_page import BacktestPage
    page = BacktestPage()
    try:
        cfg = page._read_cfg()
        assert cfg["market_filter"] is True
        assert cfg["market_filter_mode"] == "strong"
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
