# -*- coding: utf-8 -*-
"""
回测管理页：配置 → 运行（后台线程）→ 指标 + 净值曲线 + 交易明细。
回测引擎见 backtest.py，策略配置与实时扫描共用（界面迭代立即生效）。
"""
from __future__ import annotations


import json
import os
import time
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QProgressBar, QTableWidget,
    QTableWidgetItem, QGroupBox, QMessageBox, QHeaderView, QFileDialog,
    QAbstractItemView, QToolButton, QScrollArea, QFrame, QApplication,
    QCheckBox,
)

from strategy_schema import (
    DEFAULT_FACTOR_DEFS, V9_STRATEGIES,
    load_strategy_config, build_factor_defs,
)
from backtest import run_backtest, DEFAULT_BT_CONFIG

BT_RESULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "backtest_results")


class BacktestWorker(QThread):
    """后台回测线程"""
    progress = Signal(str, int)   # (msg, pct)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            result = run_backtest(self.cfg, progress_cb=self._on_progress)
            if self._stop:
                return
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa
            import traceback
            traceback.print_exc()
            self.failed.emit(str(exc))

    def _on_progress(self, msg: str, pct: int):
        self.progress.emit(msg, pct)


class EquityChart(QWidget):
    """自绘净值曲线"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.equity: List[List] = []
        self.setMinimumHeight(220)

    def set_data(self, equity: List[List]):
        self.equity = equity or []
        self.update()

    def paintEvent(self, event):  # noqa
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        if not self.equity:
            p.setPen(QColor("#999999"))
            p.drawText(self.rect(), Qt.AlignCenter, "运行回测后显示净值曲线")
            return
        navs = [float(x[1]) for x in self.equity]
        lo, hi = min(navs), max(navs)
        if hi - lo < 1e-9:
            hi = lo + 1.0
        pad_l, pad_r, pad_t, pad_b = 46, 12, 12, 20
        pw, ph = w - pad_l - pad_r, h - pad_t - pad_b

        # 网格 + 基准 1.0
        p.setPen(QPen(QColor("#dddddd"), 1))
        for i in range(5):
            y = pad_t + ph * i / 4
            p.drawLine(pad_l, int(y), w - pad_r, int(y))
            val = hi - (hi - lo) * i / 4
            p.setPen(QColor("#888888"))
            p.drawText(2, int(y) + 4, pad_l - 6, 14,
                       Qt.AlignRight | Qt.AlignVCenter, f"{val:.2f}")
            p.setPen(QPen(QColor("#dddddd"), 1))
        # 基准线（1.0 相对净值）
        base_y = pad_t + ph * (hi - 1.0) / (hi - lo) if hi > lo else pad_t + ph
        p.setPen(QPen(QColor("#9e9e9e"), 1, Qt.DashLine))
        p.drawLine(pad_l, int(base_y), w - pad_r, int(base_y))

        # 净值曲线
        p.setPen(QPen(QColor("#1e88e5"), 2))
        n = len(navs)
        if n == 1:
            return
        prev_pt = None
        for i, nav in enumerate(navs):
            x = pad_l + pw * i / (n - 1)
            y = pad_t + ph * (hi - nav) / (hi - lo)
            pt = (int(x), int(y))
            if prev_pt:
                p.drawLine(*prev_pt, *pt)
            prev_pt = pt
        # 首尾日期
        p.setPen(QColor("#666666"))
        p.drawText(pad_l, h - 4, self.equity[0][0])
        p.drawText(w - pad_r - 80, h - 4, self.equity[-1][0])
        p.end()


class BacktestPage(QWidget):
    """回测管理界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: Optional[BacktestWorker] = None
        self.last_result: Optional[dict] = None
        self._hits_codes: List[str] = []
        self.strategy_provider = None  # main.py 注入：读取策略管理页未保存的编辑态
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        title = QLabel("回测管理：用本地历史验证策略，改完实现立刻验证效果")
        title.setStyleSheet("font-size:14px;font-weight:bold;margin:4px;")
        outer.addWidget(title)

        # 内容放入滚动区：窗口高度有限时，底部的交易明细不会“挤到屏幕外”
        self._outer_scroll = QScrollArea()
        self._outer_scroll.setWidgetResizable(True)
        self._outer_scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(4, 2, 4, 4)
        root.setSpacing(4)

        # 配置区
        cfg_box = QGroupBox("回测配置")
        grid = QGridLayout(cfg_box)

        self.cb_strategy = QComboBox()
        self.cb_strategy.addItem("综合因子策略（可迭代编辑）", "factor_default")
        for s in V9_STRATEGIES:
            self.cb_strategy.addItem(f"{s['name']} ({s['key']})", s["key"])
        self.cb_strategy.currentIndexChanged.connect(self._on_strategy_changed)

        self.ed_start = QLineEdit("")
        self.ed_start.setPlaceholderText("留空=最近120交易日")
        self.ed_end = QLineEdit("")
        self.ed_end.setPlaceholderText("留空=最新交易日")
        self.ed_cash = QLineEdit("6000")
        self.ed_topn = QLineEdit("10")
        self.ed_topn.setToolTip(
            "持仓数随本金自适应：每只至少约 600 元预算（≈1 手低价股），\n"
            "6000 元本金实际最多约 10 只；加大本金可自动放宽上限。")
        self.ed_hold = QLineEdit("15")
        self.ed_fee = QLineEdit("0.0005")
        self.ed_minscore = QLineEdit("55")
        self.ed_stop = QLineEdit("-12")
        self.ed_profit = QLineEdit("20")
        self.ed_rebal = QLineEdit("2")
        self.cb_universe = QComboBox()
        # 默认全A：每个历史交易日站在当日视角重新打分选股，避免拿当前选股套历史（前视偏差）
        self.cb_universe.addItem("全A（抽样）·逐日历史选股", "all")
        self.cb_universe.addItem("上次扫描命中池·仅验证当前选股", "hits")
        self.cb_universe.setToolTip(
            "全A（抽样）：在每个历史交易日用当日数据重新打分选股，"
            "买入/卖出价均为历史当日价格，无前视偏差。\n"
            "上次扫描命中池：仅用当前扫描选出的股票做历史回放，"
            "存在前视/选择偏差，仅用于验证当前选股的历史表现，结果偏乐观。")
        self.cb_universe.currentIndexChanged.connect(self._on_universe_changed)
        self.ed_maxcodes = QLineEdit("400")
        self.chk_market = QCheckBox("大盘过滤")
        self.chk_market.setChecked(True)
        self.chk_market.setToolTip(
            "回测区间内，全池等权指数跌破其 20 日线时跳过买入（空仓等待），"
            "可大幅减少震荡/下跌市的无效交易与回撤。")
        self.ed_maxbuy = QLineEdit("6")
        self.ed_maxbuy.setToolTip(
            "调仓日当日涨幅超过该值(%)的股票不追高买入（避免买在情绪高点/涨停日）；"
            "留空或填 0 表示不限制")

        grid.addWidget(QLabel("策略"), 0, 0)
        grid.addWidget(self.cb_strategy, 0, 1)
        grid.addWidget(QLabel("起止日期"), 0, 2)
        grid.addWidget(self.ed_start, 0, 3)
        grid.addWidget(self.ed_end, 0, 4)
        grid.addWidget(QLabel("初始资金"), 1, 0)
        grid.addWidget(self.ed_cash, 1, 1)
        grid.addWidget(QLabel("买入TopN"), 1, 2)
        grid.addWidget(self.ed_topn, 1, 3)
        grid.addWidget(QLabel("持有天数"), 1, 4)
        grid.addWidget(self.ed_hold, 1, 5)
        grid.addWidget(QLabel("单边费率"), 2, 0)
        grid.addWidget(self.ed_fee, 2, 1)
        grid.addWidget(QLabel("买入门槛分"), 2, 2)
        grid.addWidget(self.ed_minscore, 2, 3)
        grid.addWidget(QLabel("止损%"), 2, 4)
        grid.addWidget(self.ed_stop, 2, 5)
        grid.addWidget(QLabel("止盈%"), 3, 0)
        grid.addWidget(self.ed_profit, 3, 1)
        grid.addWidget(QLabel("调仓间隔(日)"), 3, 2)
        grid.addWidget(self.ed_rebal, 3, 3)
        grid.addWidget(QLabel("标的池"), 3, 4)
        grid.addWidget(self.cb_universe, 3, 5)
        grid.addWidget(QLabel("最大标的数"), 4, 0)
        grid.addWidget(self.ed_maxcodes, 4, 1)
        grid.addWidget(self.chk_market, 4, 2)
        grid.addWidget(QLabel("不追高涨幅%"), 4, 3)
        grid.addWidget(self.ed_maxbuy, 4, 4)

        self.btn_run = QPushButton("运行回测")
        self.btn_run.clicked.connect(self._run)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_save = QPushButton("保存结果")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_result)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_save)
        grid.addLayout(btns, 5, 0, 1, 6)

        self.lbl_coverage = QLabel("")
        self.lbl_coverage.setWordWrap(True)
        self.lbl_coverage.setStyleSheet("color:#666;")
        grid.addWidget(self.lbl_coverage, 6, 0, 1, 6)

        root.addWidget(cfg_box)

        # 进度
        self.progress = QProgressBar()
        self.lbl_status = QLabel("就绪")
        root.addWidget(self.progress)
        root.addWidget(self.lbl_status)

        # 指标区
        self.metrics_widget = QWidget()
        ml = QGridLayout(self.metrics_widget)
        self.metrics_labels: Dict[str, QLabel] = {}
        keys = [("total_return", "总收益率"),
                ("annual_return", "年化收益"),
                ("max_drawdown", "最大回撤"),
                ("sharpe", "夏普比率"),
                ("win_rate", "胜率"),
                ("profit_factor", "盈亏比"),
                ("trade_count", "交易次数"),
                ("days", "回测天数")]
        for i, (k, name) in enumerate(keys):
            lab = QLabel(f"{name}: —")
            lab.setStyleSheet("font-size:13px;font-weight:bold;padding:4px;")
            self.metrics_labels[k] = lab
            ml.addWidget(lab, i // 4, i % 4)
        root.addWidget(self.metrics_widget)
        self.metrics_widget.hide()

        # 净值曲线（可折叠，默认折叠：窗口高度有限时优先保证交易明细可见）
        self.chart = EquityChart()
        root.addWidget(self._make_section_bar("净值曲线", self.chart, checked=False))
        root.addWidget(self.chart)

        # 交易明细（可折叠，默认展开）
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            ["代码", "名称", "买入日", "买入价", "卖出日", "卖出价",
             "股数", "盈亏(元)", "盈亏%", "原因"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(240)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # 表格滚动到边界时把滚轮转发给外层滚动区，避免表格把页面滚动“吃掉”
        self.table.viewport().installEventFilter(self)
        root.addWidget(self._make_section_bar("交易明细", self.table, checked=True))
        root.addWidget(self.table, 1)

        self._outer_scroll.setWidget(content)
        outer.addWidget(self._outer_scroll, 1)

        self._on_strategy_changed()

    def _make_section_bar(self, title: str, target: QWidget,
                          checked: bool = True) -> QToolButton:
        """生成一个可折叠区域标题栏：点击展开/收起 target。"""
        btn = QToolButton()
        btn.setText(title)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setStyleSheet(
            "QToolButton { border:none; font-size:13px; font-weight:bold;"
            " color:#333; padding:3px 2px; }"
            "QToolButton:hover { color:#1e88e5; }")
        btn.toggled.connect(
            lambda checked, b=btn, w=target: self._toggle_section(b, w, checked))
        return btn

    def _toggle_section(self, btn: QToolButton, target: QWidget, checked: bool):
        target.setVisible(checked)
        btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def eventFilter(self, obj, event):  # noqa: N802
        # 交易明细滚动到顶部/底部边界时，把滚轮事件转发给外层滚动区
        table = getattr(self, "table", None)
        if (table is not None and obj is table.viewport()
                and event.type() == QEvent.Type.Wheel
                and getattr(self, "_outer_scroll", None) is not None):
            sb = table.verticalScrollBar()
            dy = event.angleDelta().y()
            at_edge = (dy > 0 and sb.value() <= sb.minimum()) or \
                      (dy < 0 and sb.value() >= sb.maximum())
            if at_edge:
                QApplication.sendEvent(self._outer_scroll.viewport(), event)
                return True
        return super().eventFilter(obj, event)

    def _on_strategy_changed(self):
        key = self.cb_strategy.currentData()
        base = ""
        if key == "factor_default":
            base = ("综合因子策略：回测仅覆盖本地历史(L)可回放因子 "
                    "（板块环境/题材/市场环境无历史回放数据；在线/实时因子不参与回测）")
        else:
            for s in V9_STRATEGIES:
                if s["key"] == key:
                    base = (f"{s['name']}：硬条件策略。在线字段在历史中无数据，"
                            f"回测仅评估其本地硬条件部分（结果仅供参考）。")
                    break
        self._lbl_coverage_base = base
        self._refresh_coverage()

    def _on_universe_changed(self):
        self._refresh_coverage()

    def _refresh_coverage(self):
        mode = self.cb_universe.currentData()
        if mode == "hits":
            self.lbl_coverage.setText(
                self._lbl_coverage_base +
                " | 标的池=上次扫描命中池：仅验证当前选股的历史表现，"
                "存在前视/选择偏差，结果偏乐观")
        else:
            self.lbl_coverage.setText(
                self._lbl_coverage_base +
                " | 标的池=全A(抽样)：每个历史交易日按当日数据重新选股，"
                "价格均为历史当日价格，无前视偏差")

    def set_hits_codes(self, codes: List[str]):
        self._hits_codes = codes or []

    # ---------- 运行 ----------
    def _read_cfg(self) -> dict:
        def _f(x, dflt):
            try:
                return float(x.text().strip())
            except (ValueError, AttributeError):
                return dflt

        return {
            "strategy": self.cb_strategy.currentData(),
            "start": self.ed_start.text().strip(),
            "end": self.ed_end.text().strip(),
            "init_cash": _f(self.ed_cash, DEFAULT_BT_CONFIG["init_cash"]),
            "top_n": int(_f(self.ed_topn, DEFAULT_BT_CONFIG["top_n"])),
            "hold_days": int(_f(self.ed_hold, DEFAULT_BT_CONFIG["hold_days"])),
            "fee_rate": _f(self.ed_fee, DEFAULT_BT_CONFIG["fee_rate"]),
            "min_score": _f(self.ed_minscore, DEFAULT_BT_CONFIG["min_score"]),
            "stop_loss": _f(self.ed_stop, DEFAULT_BT_CONFIG["stop_loss"]),
            "take_profit": _f(self.ed_profit, DEFAULT_BT_CONFIG["take_profit"]),
            "rebalance_every": max(1, int(_f(self.ed_rebal, DEFAULT_BT_CONFIG["rebalance_every"]))),
            "universe": self.cb_universe.currentData(),
            "max_codes": int(_f(self.ed_maxcodes, 400)),
            "market_filter": self.chk_market.isChecked(),
            "market_filter_mode": "strong",   # 指数>20日线 且 20日线走多
            "ma_up_days": 3,
            "max_buy_pct": (lambda s: None if not s.strip() else
                            (_f(self.ed_maxbuy, DEFAULT_BT_CONFIG["max_buy_pct"]) or None))(
                self.ed_maxbuy.text()),
            "hits_codes": self._hits_codes,
            # 优先取策略管理页未保存的编辑态；无 provider 时回退已保存配置
            "config": (self.strategy_provider() if self.strategy_provider
                       else load_strategy_config()),
        }

    def _run(self):
        if self.worker and self.worker.isRunning():
            return
        cfg = self._read_cfg()
        self.progress.setValue(0)
        self.lbl_status.setText("准备中...")
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker = BacktestWorker(cfg, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_error)
        self.worker.start()

    def _stop(self):
        if self.worker:
            self.worker.stop()
            self.lbl_status.setText("正在停止...")

    def _on_progress(self, msg: str, pct: int):
        self.progress.setValue(max(0, min(pct, 100)))
        self.lbl_status.setText(msg)

    def _on_done(self, result: dict):
        self.last_result = result
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_save.setEnabled(True)
        m = result["metrics"]
        self.metrics_widget.show()
        color = "#c62828" if m["total_return"] < 0 else "#2e7d32"
        self.metrics_labels["total_return"].setStyleSheet(
            f"font-size:13px;font-weight:bold;padding:4px;color:{color};")
        self.metrics_labels["total_return"].setText(f"总收益率: {m['total_return']}%")
        self.metrics_labels["annual_return"].setText(f"年化收益: {m['annual_return']}%")
        self.metrics_labels["max_drawdown"].setText(f"最大回撤: {m['max_drawdown']}%")
        self.metrics_labels["sharpe"].setText(f"夏普比率: {m['sharpe']}")
        self.metrics_labels["win_rate"].setText(f"胜率: {m['win_rate']}%")
        self.metrics_labels["profit_factor"].setText(f"盈亏比: {m['profit_factor']}")
        self.metrics_labels["trade_count"].setText(f"交易次数: {m['trade_count']}")
        self.metrics_labels["days"].setText(f"回测天数: {m['days']}")
        cov = result["coverage"]
        self.lbl_coverage.setText(
            f"参与因子: {len(cov['factors'])} 个 ({', '.join(cov['factors'])}) | "
            f"未参与: {', '.join(cov['excluded']) if cov['excluded'] else '无'} | "
            f"耗时 {result['elapsed']}s")
        self.chart.set_data(result["equity"])
        self._fill_trades(result["trades"])
        self.lbl_status.setText(f"回测完成，共 {len(result['trades'])} 笔交易")

    def _fill_trades(self, trades: List[dict]):
        self.table.setRowCount(len(trades))
        for i, t in enumerate(trades):
            vals = [t.get("code", ""), t.get("name", ""), t.get("buy_date", ""),
                    str(t.get("buy_price", "")), t.get("sell_date", ""),
                    str(t.get("sell_price", "")), str(t.get("shares", "")),
                    str(t.get("pnl", "")), str(t.get("pnl_pct", "")),
                    t.get("reason", "")]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if j in (7, 8):
                    item.setForeground(QColor(
                        "#2e7d32" if (t.get("pnl") or 0) >= 0 else "#c62828"))
                self.table.setItem(i, j, item)

    def _on_error(self, msg: str):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText(f"回测失败：{msg}")
        QMessageBox.warning(self, "回测失败", msg)

    def _save_result(self):
        if not self.last_result:
            return
        os.makedirs(BT_RESULT_DIR, exist_ok=True)
        name = time.strftime("bt_%Y%m%d_%H%M%S.json")
        path = os.path.join(BT_RESULT_DIR, name)
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(self.last_result, fp, ensure_ascii=False, indent=2,
                          default=str)
            QMessageBox.information(self, "已保存", f"回测结果已保存：\n{path}")
        except Exception as exc:  # noqa
            QMessageBox.warning(self, "保存失败", str(exc))
