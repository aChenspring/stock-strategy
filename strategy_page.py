# -*- coding: utf-8 -*-
"""
策略管理页：层级树展示「策略→复合因子→子因子→基础字段」，
支持在界面迭代调整权重/阈值/开关，保存后扫描与回测即时生效。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QLabel, QPushButton, QLineEdit,
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QTextEdit, QMessageBox,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt

from strategy_schema import (
    BASIC_FIELDS, SRC_LOCAL, SRC_ONLINE, SRC_REALTIME,
    SRC_LABEL, SRC_COLOR,
    DEFAULT_FACTOR_DEFS, V9_STRATEGIES,
    build_factor_defs, build_rules_map, default_rules,
    load_strategy_config, save_strategy_config, reset_strategy_config,
    build_pipe_plan,
)

_ROLE_KEY = Qt.UserRole
_ROLE_TYPE = Qt.UserRole + 1
_ROLE_FACTOR = Qt.UserRole + 2
_ROLE_RULE = Qt.UserRole + 3

T_FACTOR = "factor"
T_RULE = "rule"
T_STRATEGY = "strategy"

_OPS = [(">", ">"), (">=", ">="), ("<", "<"), ("<=", "<="),
        ("==", "=="), ("!=", "!="), ("between", "between"),
        ("in", "in"), ("bool_true", "为真"), ("bool_false", "为假"),
        ("always", "恒真")]


class StrategyPage(QWidget):
    """策略管理界面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = load_strategy_config()
        self.factor_defs = build_factor_defs(self.cfg)
        self.rules_map = build_rules_map(self.cfg)
        self._current_factor: Optional[str] = None
        self._current_rule: Optional[tuple] = None   # (factor_key, rule_id)
        self._current_strategy: Optional[str] = None
        self._build_ui()
        self._rebuild_tree()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("策略管理：自上而下 策略 → 复合因子 → 子因子 → 基础字段")
        title.setStyleSheet("font-size:14px;font-weight:bold;margin:4px;")
        root.addWidget(title)

        split = QSplitter(Qt.Horizontal)

        # 左：层级树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["层级结构（点击右侧编辑参数）"])
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        split.addWidget(self.tree)

        # 右：编辑区
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)

        self.edit_group = QGroupBox("参数编辑")
        form = QFormLayout(self.edit_group)
        self.ed_name = QLabel("—")
        self.ed_source = QLabel("—")
        self.ed_weight = QLineEdit()
        self.ed_weight.setPlaceholderText("权重（可正可负）")
        self.ed_op = QComboBox()
        for text, val in _OPS:
            self.ed_op.addItem(f"{text}", val)
        self.ed_value = QLineEdit()
        self.ed_value.setPlaceholderText("阈值：数字 / [a,b] 区间 / 列表")
        self.ed_enable = QCheckBox("启用该规则")
        form.addRow("名称", self.ed_name)
        form.addRow("数据源", self.ed_source)
        form.addRow("权重", self.ed_weight)
        form.addRow("算子", self.ed_op)
        form.addRow("阈值", self.ed_value)
        form.addRow("", self.ed_enable)
        self.ed_hint = QLabel("提示：选中左侧节点后在此编辑")
        self.ed_hint.setWordWrap(True)
        self.ed_hint.setStyleSheet("color:#666;")
        form.addRow("", self.ed_hint)
        rl.addWidget(self.edit_group)

        btns = QHBoxLayout()
        self.btn_apply = QPushButton("应用到当前节点")
        self.btn_apply.clicked.connect(self._apply_edit)
        self.btn_save = QPushButton("保存全部配置")
        self.btn_save.clicked.connect(self._save)
        self.btn_reset = QPushButton("恢复默认")
        self.btn_reset.clicked.connect(self._reset)
        btns.addWidget(self.btn_apply)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_reset)
        rl.addLayout(btns)

        # pipe 计划
        pipe_group = QGroupBox("动态 pipe 计划（数据源感知：哪些 key 复用 / 替换 / 新增）")
        pl = QVBoxLayout(pipe_group)
        self.pipe_text = QTextEdit()
        self.pipe_text.setReadOnly(True)
        self.pipe_text.setMaximumHeight(170)
        self.pipe_text.setStyleSheet("font-family:Consolas,monospace;font-size:12px;")
        pl.addWidget(self.pipe_text)
        self.btn_plan = QPushButton("按当前策略刷新 pipe 计划")
        self.btn_plan.clicked.connect(self._refresh_plan)
        pl.addWidget(self.btn_plan)
        rl.addWidget(pipe_group)

        split.addWidget(right)
        split.setSizes([380, 620])
        root.addWidget(split)
        self._refresh_plan()

    # ---------- 树构建 ----------
    def _rebuild_tree(self):
        self.tree.clear()
        self.tree.blockSignals(True)
        root = QTreeWidgetItem(["策略"])
        root.setExpanded(True)
        self.tree.addTopLevelItem(root)

        # 综合因子策略
        sitem = QTreeWidgetItem(root, ["综合因子策略 factor_default（可迭代编辑）"])
        sitem.setData(0, _ROLE_TYPE, T_STRATEGY)
        sitem.setData(0, _ROLE_KEY, "factor_default")
        for f in self.factor_defs:
            fitem = QTreeWidgetItem(sitem, [self._factor_title(f)])
            fitem.setData(0, _ROLE_TYPE, T_FACTOR)
            fitem.setData(0, _ROLE_KEY, f["key"])
            src = f.get("source", SRC_LOCAL)
            fitem.setForeground(0, _color_brush(src))
            for r in self.rules_map.get(f["key"], []):
                ritem = QTreeWidgetItem(fitem, [self._rule_title(r)])
                ritem.setData(0, _ROLE_TYPE, T_RULE)
                ritem.setData(0, _ROLE_KEY, f["key"])
                ritem.setData(0, _ROLE_RULE, r.get("id", ""))
                ritem.setForeground(0, _color_brush(r.get("source", src)))
                bf = BASIC_FIELDS.get(r["field"])
                btxt = r["field"]
                if bf:
                    btxt = f"{r['field']}  ({bf['label']} · {SRC_LABEL.get(bf['source'], '')})"
                bitem = QTreeWidgetItem(ritem, [btxt])
                bitem.setForeground(0, _color_brush(r.get("source", src)))
                bitem.setData(0, _ROLE_TYPE, "field")
        sitem.setExpanded(True)
        root.addChild(sitem)

        # v9 策略
        for s in V9_STRATEGIES:
            v = QTreeWidgetItem(root, [f"{s['name']} ({s['key']})"])
            v.setData(0, _ROLE_TYPE, T_STRATEGY)
            v.setData(0, _ROLE_KEY, s["key"])
            v.setForeground(0, _color_brush(s.get("source", SRC_LOCAL)))
            hint = QTreeWidgetItem(v, [f"硬条件内置实现 · 依赖 {SRC_LABEL.get(s['source'])} 数据"])
            hint.setForeground(0, _color_brush(s.get("source", SRC_LOCAL)))

        self.tree.expandToDepth(1)
        self.tree.blockSignals(False)

    def _factor_title(self, f: dict) -> str:
        st = "开" if f.get("enabled", True) else "关"
        src = SRC_LABEL.get(f.get("source", SRC_LOCAL), "")
        bt = "" if f.get("backtestable", True) else " [不可回测]"
        return (f"{f['name']}  [{f['key']}] 权重={f['weight']} {st} · {src}{bt}")

    def _rule_title(self, r: dict) -> str:
        st = "开" if r.get("enabled", True) else "关"
        w = r.get("weight", 0.0)
        return f"{r['name']}  ({w:+.2f}) {st}"

    # ---------- 选择 ----------
    def _on_selection(self):
        items = self.tree.selectedItems()
        if not items:
            return
        it = items[0]
        t = it.data(0, _ROLE_TYPE)
        key = it.data(0, _ROLE_KEY)
        if t == T_FACTOR:
            self._current_factor = key
            self._current_rule = None
            self._current_strategy = None
            self._show_factor_editor(key)
        elif t == T_RULE:
            rid = it.data(0, _ROLE_RULE)
            self._current_factor = key
            self._current_rule = (key, rid)
            self._current_strategy = None
            self._show_rule_editor(key, rid)
        elif t == T_STRATEGY:
            self._current_factor = None
            self._current_rule = None
            self._current_strategy = key
            self._show_strategy_info(key)
        else:
            self._current_factor = None
            self._current_rule = None
            self._current_strategy = None
            self._clear_editor("选中节点为只读展示（字段/数据源）")

    def _clear_editor(self, hint: str):
        self.ed_name.setText("—")
        self.ed_source.setText("—")
        self.ed_weight.setText("")
        self.ed_value.setText("")
        self.ed_enable.setChecked(False)
        self.ed_op.setCurrentIndex(0)
        self.ed_hint.setText(hint)

    def _show_factor_editor(self, key: str):
        f = next((x for x in self.factor_defs if x["key"] == key), None)
        if not f:
            return
        src = f.get("source", SRC_LOCAL)
        self.ed_name.setText(f"{f['name']} [{key}]")
        self.ed_source.setText(f"{SRC_LABEL.get(src)} · 复合因子权重参与总分合成")
        self.ed_weight.setText(str(f.get("weight", 0.05)))
        self.ed_value.setText("")
        self.ed_op.setCurrentIndex(0)
        self.ed_enable.setChecked(f.get("enabled", True))
        rules = self.rules_map.get(key, [])
        self.ed_hint.setText(f"共 {len(rules)} 条子因子规则；修改权重后点「应用到当前节点」。")

    def _show_rule_editor(self, key: str, rid: str):
        f = next((x for x in self.factor_defs if x["key"] == key), None)
        r = next((x for x in self.rules_map.get(key, []) if x.get("id") == rid), None)
        if not f or not r:
            return
        bf = BASIC_FIELDS.get(r["field"])
        self.ed_name.setText(f"{r['name']} [{rid}]")
        src = r.get("source", SRC_LOCAL)
        self.ed_source.setText(f"{SRC_LABEL.get(src)} · 字段 {r['field']}"
                               + (f"（{bf['label']}）" if bf else ""))
        self.ed_weight.setText(str(r.get("weight", 0.0)))
        idx = self.ed_op.findData(r.get("op", ">"))
        self.ed_op.setCurrentIndex(max(0, idx))
        v = r.get("value")
        self.ed_value.setText("" if v is None else str(v))
        self.ed_enable.setChecked(r.get("enabled", True))
        self.ed_hint.setText(r.get("desc", ""))

    def _show_strategy_info(self, key: str):
        if key == "factor_default":
            self.ed_name.setText("综合因子策略")
            self.ed_source.setText("可迭代编辑：权重/阈值/开关 全部可调")
            self.ed_weight.setText("")
            self.ed_value.setText("")
            self.ed_op.setCurrentIndex(0)
            self.ed_enable.setChecked(True)
            self.ed_hint.setText("由上方 14 个复合因子加权合成 0-100 综合分。")
            return
        for s in V9_STRATEGIES:
            if s["key"] == key:
                self.ed_name.setText(s["name"])
                self.ed_source.setText(f"数据源 {SRC_LABEL.get(s['source'])}")
                self.ed_weight.setText("")
                self.ed_value.setText("")
                self.ed_op.setCurrentIndex(0)
                self.ed_enable.setChecked(True)
                self.ed_hint.setText(s["desc"])
                return

    # ---------- 编辑 ----------
    def _apply_edit(self):
        try:
            w = float(self.ed_weight.text().strip() or "0")
        except ValueError:
            QMessageBox.warning(self, "输入错误", "权重必须是数字")
            return
        if self._current_factor and self._current_rule is None and self._current_strategy is None:
            for f in self.factor_defs:
                if f["key"] == self._current_factor:
                    f["weight"] = w
                    f["enabled"] = self.ed_enable.isChecked()
                    break
            self._rebuild_tree()
            self.ed_hint.setText("已应用：因子权重/开关更新。点「保存全部配置」持久化。")
        elif self._current_rule:
            fkey, rid = self._current_rule
            r = next((x for x in self.rules_map.get(fkey, []) if x.get("id") == rid), None)
            if r:
                r["weight"] = w
                r["enabled"] = self.ed_enable.isChecked()
                op = self.ed_op.currentData()
                if op:
                    r["op"] = op
                raw = self.ed_value.text().strip()
                if raw:
                    r["value"] = _parse_value(raw)
                elif op not in ("bool_true", "bool_false", "always"):
                    r["value"] = None
                self._rebuild_tree()
                self.ed_hint.setText("已应用：子因子规则更新。点「保存全部配置」持久化。")
        else:
            self.ed_hint.setText("请先选中一个复合因子或子因子节点。")

    def _save(self):
        # 因子级
        cfg = {
            "factor_weights": {f["key"]: f["weight"] for f in self.factor_defs},
            "factor_enabled": {f["key"]: bool(f.get("enabled", True)) for f in self.factor_defs},
        }
        # 规则级（只存可编辑字段）
        rules = {}
        for key, rs in self.rules_map.items():
            rules[key] = [{"id": r["id"], "weight": r.get("weight", 0.0),
                           "op": r.get("op", ">"),
                           "value": r.get("value"),
                           "enabled": bool(r.get("enabled", True))}
                          for r in rs]
        cfg["rules"] = rules
        if save_strategy_config(cfg):
            QMessageBox.information(self, "已保存",
                                    "配置已写入 strategy_config.json。\n"
                                    "扫描与回测将按新配置执行。")
        else:
            QMessageBox.warning(self, "失败", "配置写入失败")

    def _reset(self):
        if QMessageBox.question(self, "确认", "恢复全部默认策略配置？") \
                == QMessageBox.Yes:
            reset_strategy_config()
            self.cfg = {}
            self.factor_defs = build_factor_defs(None)
            self.rules_map = build_rules_map(None)
            self._rebuild_tree()
            self._refresh_plan()
            self._clear_editor("已恢复默认配置")

    def _refresh_plan(self):
        key = self._current_strategy or "factor_default"
        plan = build_pipe_plan(key, self.cfg)
        lines = [f"== 当前策略：{key} ==", ""]
        for src, g in plan["groups"].items():
            lines.append(f"[{g['label']}] {g['action']}")
            lines.append(f"  字段: {', '.join(g['fields']) if g['fields'] else '（无）'}")
            lines.append("")
        if plan["reuse"]:
            lines.append("复用（不重算）：")
            lines.extend(f"  ✓ {x}" for x in plan["reuse"])
        if plan["replace"]:
            lines.append("替换（需重拉）：")
            lines.extend(f"  ↻ {x}" for x in plan["replace"])
        if plan["add"]:
            lines.append("动态新增（pipe 任务）：")
            lines.extend(f"  + {x}" for x in plan["add"])
        self.pipe_text.setPlainText("\n".join(lines))

    def current_config(self) -> dict:
        """供外部（扫描/回测）读取当前编辑态配置。"""
        return {
            "factor_weights": {f["key"]: f["weight"] for f in self.factor_defs},
            "factor_enabled": {f["key"]: bool(f.get("enabled", True)) for f in self.factor_defs},
            "rules": {k: [{"id": r["id"], "weight": r.get("weight", 0.0),
                           "op": r.get("op", ">"), "value": r.get("value"),
                           "enabled": bool(r.get("enabled", True))}
                          for r in rs] for k, rs in self.rules_map.items()},
        }


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        try:
            return [_num(x) for x in raw[1:-1].split(",")]
        except Exception:
            return raw
    if "," in raw:
        try:
            return [_num(x) for x in raw.split(",")]
        except Exception:
            return raw
    return _num(raw)


def _num(s: str):
    try:
        return float(s)
    except ValueError:
        return s


def _color_brush(src: str):
    from PySide6.QtGui import QBrush, QColor
    return QBrush(QColor(SRC_COLOR.get(src, "#333333")))


# 兼容旧引用
DEFAULT_RULES = default_rules()
