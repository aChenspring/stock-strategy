# -*- coding: utf-8 -*-
"""
v9 股票策略界面 - PySide6 主程序
功能：策略选择、全市场扫描、14因子评分倒序、点击查看K线
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import Any, Dict, List, Optional

# 注意：必须先导入数据/策略模块（它们会加载 stock_sdk/stockdb.pyd），
# 再导入 PySide6。否则 PySide6 的 shibokensupport 签名钩子会因 inspect
# 二进制扩展模块 stockdb.pyd 而抛 ValueError("wrapper loop")。
# 且必须 warm_default_connection()：它会触发 `import zhibiao`（zb/bk 的真正实现），
# 若留到 PySide6 导入后再首次调用 zb/bk，会触发同样的 wrapper loop 异常。
from stock_sdk import bk, warm_default_connection
warm_default_connection()
from strategy_data import (
    MarketCache, OnlineData, load_market_rows, valid_trading_rows,
    compute_indicators, compute_board_env, compute_market_env,
    build_industry_tree, load_industry_tree, save_industry_tree,
    aggregate_recent, guess_board, load_stock_boards, judge_yaogu,
    save_factor_snapshot, load_factor_snapshot, query_factor_scores,
    filter_factor_table, factor_freshness,
    START as START, END as END,
)
from factors import score_stock, FACTORS
from strategies import get_strategies, check_strategy, risk_warnings
from strategy_schema import build_factor_defs
import backtest  # noqa: F401  提前加载（含 warm），避免 PySide6 之后触发 shibokensupport

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout,
    QComboBox, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QSplitter, QMessageBox, QFrame,
    QLineEdit, QCheckBox, QGroupBox, QScrollArea, QSizePolicy,
    QFileDialog, QTableView, QAbstractItemView, QTabWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QModelIndex, QAbstractTableModel
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush

# 策略管理/回测管理页（依赖 PySide6，必须在其后导入）
from strategy_page import StrategyPage
from backtest_page import BacktestPage


# ============ 全局配置 ============
PREFIXES = ["0*", "3*", "6*", "920*"]
# START/END 从 strategy_data 动态获取（最近 6 个月到最新交易日）


# ============ 扫描工作线程 ============
def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


class ScanWorker(QThread):
    """后台扫描线程，避免阻塞UI"""
    progress = Signal(int, str)       # (百分比, 消息)
    finished_signal = Signal(list)    # 结果列表
    error_signal = Signal(str)

    def __init__(self, strategy_key: str, candidate_limit: int = 300,
                 filters: Optional[Dict[str, Any]] = None,
                 strategy_config: Optional[dict] = None):
        super().__init__()
        self.strategy_key = strategy_key
        self.candidate_limit = candidate_limit
        self.filters = filters or {}
        self.strategy_config = strategy_config or {}
        self._stop = False

    def stop(self):
        self._stop = True

    # ---------- 过滤条件 ----------
    def _passes_market_filters(self, code: str, valid: List[dict]) -> bool:
        """仅依赖行情行的快速过滤，在 compute_indicators 之前执行以提速。"""
        f = self.filters
        last = valid[-1]
        name = str(last.get("name", ""))
        close = last.get("close")
        if close is None or close <= 0:
            return False

        # 市场板块
        boards = f.get("boards", {})
        if boards and any(boards.values()):
            main = code.startswith(("60", "00"))
            gem = code.startswith("30")
            star = code.startswith("68")
            bse = code.startswith("920")
            matched = (
                (main and boards.get("main")) or
                (gem and boards.get("gem")) or
                (star and boards.get("star")) or
                (bse and boards.get("bse"))
            )
            if not matched:
                return False

        # 非ST
        if f.get("non_st") and "ST" in name.upper():
            return False

        # 股价
        price_min = f.get("price_min")
        price_max = f.get("price_max")
        if price_min is not None and close < price_min:
            return False
        if price_max is not None and close > price_max:
            return False

        # 成交额（界面单位为亿）
        amount = _safe_float(last.get("amount"))
        amount_min = f.get("amount_min")
        amount_max = f.get("amount_max")
        if amount_min is not None and (amount is None or amount < amount_min * 1e8):
            return False
        if amount_max is not None and (amount is None or amount > amount_max * 1e8):
            return False

        # 换手率
        turnover = _safe_float(last.get("turnover"))
        turnover_min = f.get("turnover_min")
        turnover_max = f.get("turnover_max")
        if turnover_min is not None and (turnover is None or turnover < turnover_min):
            return False
        if turnover_max is not None and (turnover is None or turnover > turnover_max):
            return False

        # 涨幅
        pct = _safe_float(last.get("pct_chg"))
        pct_min = f.get("pct_chg_min")
        pct_max = f.get("pct_chg_max")
        if pct_min is not None and (pct is None or pct < pct_min):
            return False
        if pct_max is not None and (pct is None or pct > pct_max):
            return False

        return True

    def _passes_indicator_filters(self, code: str, ind: Dict[str, Any],
                                  valid: List[dict]) -> bool:
        """依赖 compute_indicators 产出的技术面过滤。"""
        f = self.filters
        close = _safe_float(ind.get("close"))
        ma20 = _safe_float(ind.get("ma20"))
        ma60 = _safe_float(ind.get("ma60"))
        macd = _safe_float(ind.get("macd"))
        rsi6 = _safe_float(ind.get("rsi6"))

        if f.get("close_above_ma20"):
            if close is None or ma20 is None or close <= ma20:
                return False
        if f.get("ma20_above_ma60"):
            if ma20 is None or ma60 is None or ma20 <= ma60:
                return False
        if f.get("close_above_ma60"):
            if close is None or ma60 is None or close <= ma60:
                return False
        if f.get("macd_positive"):
            if macd is None or macd <= 0:
                return False
        if f.get("break_high20"):
            high20 = _safe_float(ind.get("high20"))
            if close is None or high20 is None or close < high20 * 0.995:
                return False
        if f.get("limit_up_recent"):
            has_limit = any(
                (_safe_float(r.get("pct_chg")) or 0) >= 9.5
                for r in valid[-5:]
            )
            if not has_limit:
                return False

        # RSI6 范围
        rsi_min = f.get("rsi_min")
        rsi_max = f.get("rsi_max")
        if rsi_min is not None and (rsi6 is None or rsi6 < rsi_min):
            return False
        if rsi_max is not None and (rsi6 is None or rsi6 > rsi_max):
            return False

        # 量比范围
        vol_ratio = _safe_float(ind.get("vol_ratio"))
        vr_min = f.get("vol_ratio_min")
        vr_max = f.get("vol_ratio_max")
        if vr_min is not None and (vol_ratio is None or vol_ratio < vr_min):
            return False
        if vr_max is not None and (vol_ratio is None or vol_ratio > vr_max):
            return False

        return True

    def _passes_online_filters(self, code: str, valid: List[dict],
                               online: Dict[str, Any], ind: Dict[str, Any]) -> bool:
        """依赖在线财务/估值/资金流/行业的过滤。"""
        f = self.filters
        fund = online.get("fund") or {}
        val = online.get("val") or {}
        flow = online.get("flow") or {}

        # 营收同比>0
        if f.get("revenue_yoy_positive"):
            rev = _safe_float(fund.get("revenue_yoy"))
            if rev is not None and rev <= 0:
                return False
        # 净利同比>0
        if f.get("profit_yoy_positive"):
            profit = _safe_float(fund.get("profit_yoy"))
            if profit is not None and profit <= 0:
                return False
        # 经营现金流>0
        if f.get("cash_flow_positive"):
            cash = _safe_float(fund.get("operating_cash_flow"))
            if cash is not None and cash <= 0:
                return False
        # 主力净流入>0（最新交易日口径）
        if f.get("main_flow_positive"):
            main_net = _safe_float(flow.get("main_net_inflow_latest")) or _safe_float(flow.get("main_net_inflow"))
            if main_net is not None and main_net <= 0:
                return False

        # 市值（界面单位为亿，接口为元）
        market_cap = _safe_float(val.get("market_cap"))
        mc_min = f.get("market_cap_min")
        mc_max = f.get("market_cap_max")
        if mc_min is not None and (market_cap is None or market_cap < mc_min * 1e8):
            return False
        if mc_max is not None and (market_cap is None or market_cap > mc_max * 1e8):
            return False

        # PE/PB/ROE
        pe = _safe_float(val.get("pe_ratio")) or _safe_float(fund.get("pe_ratio"))
        pb = _safe_float(val.get("pb_ratio")) or _safe_float(fund.get("pb_ratio"))
        roe = _safe_float(fund.get("roe"))
        for vmin, vmax, value in (
            (f.get("pe_min"), f.get("pe_max"), pe),
            (f.get("pb_min"), f.get("pb_max"), pb),
            (f.get("roe_min"), f.get("roe_max"), roe),
        ):
            if vmin is not None and (value is None or value < vmin):
                return False
            if vmax is not None and (value is None or value > vmax):
                return False

        # 负债率上限
        debt_max = f.get("debt_max")
        if debt_max is not None:
            debt = _safe_float(fund.get("debt_to_assets"))
            if debt is None or debt > debt_max:
                return False

        # 股息率下限
        dy_min = f.get("dividend_yield_min")
        if dy_min is not None:
            dy = _safe_float(fund.get("dividend_yield"))
            if dy is None or dy < dy_min:
                return False

        # 行业过滤（三级联动：优先三级，其次二级，最后一级）
        l3 = f.get("industry_l3")
        l2 = f.get("industry_l2")
        l1 = f.get("industry_l1")
        if l3 and l3 != "全部":
            try:
                boards = bk.get(code, 3, "name")
                if not isinstance(boards, list) or l3 not in boards:
                    return False
            except Exception:
                return False
        elif l2 and l2 != "全部":
            try:
                boards = bk.get(code, 2, "name")
                if not isinstance(boards, list) or l2 not in boards:
                    return False
            except Exception:
                return False
        elif l1 and l1 != "全部":
            try:
                boards = bk.get(code, 1, "name")
                if not isinstance(boards, list) or l1 not in boards:
                    return False
            except Exception:
                return False

        # 概念板块过滤
        concept = f.get("concept")
        if concept and concept != "全部":
            try:
                boards = bk.get(code, 0, "name")
                if not isinstance(boards, list) or concept not in boards:
                    return False
            except Exception:
                return False

        return True

    def run(self):
        try:
            # 预解析策略定义：综合因子策略按 min_score 门槛判定命中，v9 策略按 check 硬条件
            self._strategy_min_score = next(
                (s.get("min_score") for s in get_strategies()
                 if s["key"] == self.strategy_key), None)

            self.progress.emit(2, "加载行情数据...")
            rows_by_code = load_market_rows(PREFIXES, START, END)
            self.progress.emit(10, f"行情加载完成，共{len(rows_by_code)}只股票")

            # 技术面初筛 + 行情过滤（最快，先缩小范围）
            candidates = {}
            for code, rows in rows_by_code.items():
                if self._stop:
                    break
                valid = valid_trading_rows(rows)
                if len(valid) < 60:
                    continue
                if not self._passes_market_filters(code, valid):
                    continue
                candidates[code] = valid
            self.progress.emit(20, f"行情过滤后候选池{len(candidates)}只")

            # 计算技术指标
            self.progress.emit(25, "计算技术指标...")
            indicators = compute_indicators(candidates)

            # 板块/行业信息（一次查询全部候选，供环境分与列表展示复用）
            self.progress.emit(28, "查询板块与行业信息...")
            board_info_map = load_stock_boards(list(candidates.keys()))

            # 板块环境 + 市场环境
            self.progress.emit(30, "计算板块与市场环境...")
            board_env = compute_board_env(candidates, board_info_map)
            market_env = compute_market_env(candidates)

            # 策略迭代：因子定义按当前配置预构建一次（粗排与线程池内只读复用）
            fdefs = build_factor_defs(self.strategy_config)

            # 粗排：本地因子快速打分，仅取前 candidate_limit 只进入在线精筛。
            # 在线查询（财务/估值/资金流）是最耗时环节，粗排可砍掉约 90% 的在线请求，
            # 是 3000+ 只全量扫描 3 小时 → 十几分钟的关键（默认候选池上限 300）。
            if self.candidate_limit and len(candidates) > self.candidate_limit:
                self.progress.emit(32, f"本地因子粗排 {len(candidates)} 只，取前 {self.candidate_limit} 只精筛...")

                def _rough(code):
                    if self._stop:
                        return code, -1.0
                    ind = indicators.get(code, {})
                    sc = score_stock(code, candidates[code], ind,
                                     board_env.get(code, 0), market_env, {},
                                     config=self.strategy_config, factor_defs=fdefs)
                    return code, (sc.get("score", 0.0) if sc else -1.0)

                with ThreadPoolExecutor(max_workers=8) as pool:
                    rough = dict(pool.map(_rough, candidates))
                top = sorted(rough, key=lambda c: rough[c], reverse=True)[:self.candidate_limit]
                candidates = {c: candidates[c] for c in top}
                self.progress.emit(35, f"粗排后精筛候选池 {len(candidates)} 只")

            # 批量加载在线财务数据（接口不可用时快速跳过）
            self.progress.emit(36, "加载在线财务数据...")
            cache = MarketCache()
            online_data = OnlineData(cache)
            online_data.fundamentals_batch(list(candidates.keys()), batch=100)
            # pipe 批量预热估值/资金流本地缓存，评分循环内逐只命中内存
            # 注意 date 必须与接口缓存键一致：valuation->latest, money_flow(days=5)->"5"
            online_data.prewarm([("val", "latest"), ("flow", "5")],
                                list(candidates.keys()))
            # 在线可用性探测：在线接口返回空列表不触发熔断，会导致每只都空转请求。
            # 采样全部为空时本次扫描内短路在线请求（评分循环直接内存返回 None）。
            if not online_data.probe_online(list(candidates.keys())):
                self.progress.emit(37, "在线数据不可用，已切换纯本地因子评分（结果不受影响）")

            total = len(candidates)
            results = []
            passed_count = 0

            def process(code):
                """单只股票评分（线程池并行执行）"""
                rows = candidates[code]
                valid = valid_trading_rows(rows)
                if not valid:
                    return None
                ind = indicators.get(code, {})
                # 获取在线数据（批量已预热，单只命中缓存；不可用时快速返回）
                fund = online_data.fundamentals(code) or {}
                val = online_data.valuation(code)
                flow = online_data.money_flow(code, days=5) or {}
                online = {"fund": fund or {}, "val": val or {}, "flow": flow}

                # 本地14因子评分（不依赖在线数据，保证全量都有分）
                # 传入已过滤的 valid，避免 score_stock 内重复 valid_trading_rows
                board_score = board_env.get(code, 0)
                scored = score_stock(code, valid, ind, board_score, market_env, online,
                                     config=self.strategy_config, factor_defs=fdefs)

                # 命中判定：指标过滤 + 在线过滤 + 策略命中。
                # 综合因子策略（factor_default）按综合分门槛命中，v9 策略按 check 硬条件命中。
                if self._strategy_min_score is not None:
                    strat_hit = scored["total"] >= self._strategy_min_score
                else:
                    strat_hit = check_strategy(self.strategy_key, valid, online, indicators=ind)
                ok = (
                    self._passes_indicator_filters(code, ind, valid)
                    and self._passes_online_filters(code, valid, online, ind)
                    and strat_hit
                )
                warnings = risk_warnings(valid, online, indicators=ind)

                # ---- 组装完整展示字段（查询日近5日口径） ----
                return self._build_result(code, valid, ind, online, scored, board_score, warnings,
                                           board_info_map, ok)

            # ---- 并行扫描评分（线程池） ----
            futs = {}
            with ThreadPoolExecutor(max_workers=8) as pool:
                for i, code in enumerate(candidates):
                    if self._stop:
                        break
                    futs[pool.submit(process, code)] = code
                for k, f in enumerate(futs):
                    r = f.result()
                    if r is not None:
                        results.append(r)
                    pct = 40 + int(k / max(len(futs), 1) * 55)
                    if k % 10 == 0 or k == len(futs) - 1:
                        self.progress.emit(pct, f"扫描 {k+1}/{len(futs)}")
            passed_count = sum(1 for r in results if r.get("passed"))

                # 排序：命中的在前（按分倒序），未命中的在后（按分倒序）
            results.sort(key=lambda x: (not x["passed"], -x["score"]))

            # 行业龙头标注：同申万一级行业内总市值最大者
            best_by_sw = {}
            for r in results:
                full = r.get("full") or {}
                sw = full.get("sw_industry")
                mv = full.get("total_mv_5d") or 0
                if sw and sw != "-" and mv:
                    if sw not in best_by_sw or mv > best_by_sw[sw][1]:
                        best_by_sw[sw] = (r["code"], mv)
            for r in results:
                full = r.get("full") or {}
                sw = full.get("sw_industry")
                mv = full.get("total_mv_5d") or 0
                if sw in best_by_sw and best_by_sw[sw][0] == r["code"] and best_by_sw[sw][1] > 0:
                    full["leader_tag"] = "是"

            # 因子快照落库（pipe.mset 批量写入，同交易日重复扫描覆盖）
            save_factor_snapshot(results, END)

            self.progress.emit(100, f"扫描完成，命中{passed_count}/{len(results)}只，未命中{len(results)-passed_count}只")
            self.finished_signal.emit(results)
        except Exception:
            import traceback
            self.error_signal.emit(traceback.format_exc())

    def _build_result(self, code, valid, ind, online, scored, board_score, warnings, board_info_map, ok):
        """组装一只股票的结果条目（含全部展示字段）。"""
        fund = online.get("fund") or {}
        val = online.get("val") or {}
        flow = online.get("flow") or {}
        last = valid[-1]
        agg = aggregate_recent(valid, 5)
        binfo = board_info_map.get(code, {})
        close = _safe_float(last.get("close"))
        pct_chg = _safe_float(last.get("pct_chg"))
        main_net_5d = _safe_float(flow.get("main_net_inflow"))
        main_latest = _safe_float(flow.get("main_net_inflow_latest"))
        revenue_yoy = _safe_float(fund.get("revenue_yoy"))
        profit_yoy = _safe_float(fund.get("profit_yoy"))
        amount_5d = agg.get("amount_5d")
        total_mv_5d = agg.get("total_mv_5d")
        full = {
            "code": code,
            "name": str(last.get("name", code)),
            "leader_tag": "",
            "yaogu_tag": judge_yaogu(valid, ind),
            "close": close,
            "pct_chg": pct_chg,
            "board": guess_board(code),
            "vol_ratio": _safe_float(last.get("vol_ratio")),
            "ths_industry": "-",
            "sw_industry": binfo.get("sw1") or binfo.get("sw2") or "-",
            "sw1": binfo.get("sw1") or "",
            "sw2": binfo.get("sw2") or "",
            "sw3": binfo.get("sw3") or "",
            "market_cap": _safe_float(val.get("market_cap")),
            "avg_close_5d": agg.get("avg_close_5d"),
            "vol_5d": agg.get("vol_5d"),
            "amount_5d": amount_5d,
            "turnover_5d": agg.get("turnover_5d"),
            "amplitude_5d": agg.get("amplitude_5d"),
            "total_mv_5d": total_mv_5d,
            "float_mv_5d": agg.get("float_mv_5d"),
            "pe_ttm": _safe_float(last.get("pe_ttm")),
            "pb": _safe_float(last.get("pb")),
            "dividend_yield": _safe_float(fund.get("dividend_yield")),
            "main_net_latest": main_latest,
            "inflow_5d": _safe_float(flow.get("inflow")),
            "outflow_5d": _safe_float(flow.get("outflow")),
            "revenue": _safe_float(fund.get("revenue")),
            "net_profit": _safe_float(fund.get("net_profit")),
            "revenue_yoy": revenue_yoy,
            "profit_yoy": profit_yoy,
            "deducted_profit": _safe_float(fund.get("deducted_profit")),
            "deducted_yoy": _safe_float(fund.get("deducted_yoy")),
            "gross_margin": _safe_float(fund.get("gross_margin")),
            "net_profit_margin": _safe_float(fund.get("net_profit_margin")),
            "roe": _safe_float(fund.get("roe")),
            "debt_to_assets": _safe_float(fund.get("debt_to_assets")),
            "eps": _safe_float(fund.get("eps")),
            "bps": _safe_float(fund.get("bps")),
            "ocf": _safe_float(fund.get("operating_cash_flow")),
            "rd_expense": _safe_float(fund.get("rd_expense")),
            "ma5": _safe_float(ind.get("ma5")),
            "ma10": _safe_float(ind.get("ma10")),
            "ma20": _safe_float(ind.get("ma20")),
            "ma60": _safe_float(ind.get("ma60")),
            "macd": _safe_float(ind.get("macd")),
            "dif": _safe_float(ind.get("dif")),
            "dea": _safe_float(ind.get("dea")),
            "kdj": _safe_float(ind.get("j")),
            "kdj_k": _safe_float(ind.get("k")),
            "kdj_d": _safe_float(ind.get("d")),
            "kdj_j": _safe_float(ind.get("j")),
            "rsi6": _safe_float(ind.get("rsi6")),
            "rsi12": _safe_float(ind.get("rsi12")),
            "rsi24": _safe_float(ind.get("rsi24")),
            "boll_mid": _safe_float(ind.get("boll_mid")),
            "boll_lower": _safe_float(ind.get("boll_lower")),
            "boll_upper": _safe_float(ind.get("boll_upper")),
            "obv": _safe_float(ind.get("obv")),
            "province": "-",
            "city": "-",
            "concepts": binfo.get("concepts") or "-",
            "index_class": "-",
            "market_type": "A股",
            "main_net_5d_yi": main_net_5d / 1e8 if main_net_5d is not None else None,
            "amount_5d_yi": amount_5d / 1e8 if amount_5d else None,
            "total_mv_yi": total_mv_5d / 1e8 if total_mv_5d else None,
            "revenue_yoy_abs": revenue_yoy,
            "profit_yoy_abs": profit_yoy,
        }
        return {
            "code": code,
            "name": str(last.get("name", code)),
            "score": round(scored["total"], 2),
            "passed": ok,
            "factor_scores": scored["factor_scores"],
            "details": scored["details"],
            "warnings": warnings,
            "close": close,
            "pct_chg": pct_chg,
            "amount": scored["details"].get("amount"),
            "turnover": scored["details"].get("turnover"),
            "vol_ratio": scored["details"].get("vol_ratio"),
            "board_score": board_score,
            "full": full,
        }


# ============ 结果表格列定义 ============
# (key, 表头)。key 对应 results[].full 中的字段；带日期的字段统一为"查询日近5日"口径。
RESULT_COLUMNS = [
    ("code", "股票代码"),
    ("name", "股票简称"),
    ("leader_tag", "龙头"),
    ("yaogu_tag", "妖股气质"),
    ("score", "综合分"),
    ("close", "最新价(元)"),
    ("pct_chg", "最新涨跌幅(%)"),
    ("board", "上市板块"),
    ("vol_ratio", "量比"),
    ("ths_industry", "所属同花顺行业"),
    ("sw_industry", "所属申万行业"),
    ("avg_close_5d", "收盘价[近5日](元)"),
    ("vol_5d", "成交量[近5日](股)"),
    ("amount_5d", "成交额[近5日](元)"),
    ("turnover_5d", "换手率[近5日](%)"),
    ("amplitude_5d", "振幅[近5日](%)"),
    ("total_mv_5d", "总市值[近5日](元)"),
    ("float_mv_5d", "流通市值[近5日](元)"),
    ("pe_ttm", "最新市盈率ttm"),
    ("pb", "最新市净率"),
    ("dividend_yield", "年度股息率[20251231](%)"),
    ("main_net_latest", "主力资金流向(元)"),
    ("inflow_5d", "资金流入[近5日](元)"),
    ("outflow_5d", "资金流出[近5日](元)"),
    ("revenue", "营业收入(元)"),
    ("net_profit", "归母净利润(元)"),
    ("revenue_yoy", "营业收入同比增长率(%)"),
    ("profit_yoy", "归母净利润同比增长率(%)"),
    ("deducted_profit", "扣非归母净利润[20260630](元)"),
    ("deducted_yoy", "扣非净利润同比增长率[20260630](%)"),
    ("gross_margin", "销售毛利率[20260630](%)"),
    ("net_profit_margin", "销售净利率[20260630](%)"),
    ("roe", "净资产收益率[20260630](%)"),
    ("debt_to_assets", "资产负债率[20260630](%)"),
    ("eps", "基本每股收益[20260630](元)"),
    ("bps", "每股净资产[20260630](元)"),
    ("ocf", "经营活动产生的现金流量净额[20260630](元)"),
    ("rd_expense", "研发费用[20260630](元)"),
    ("ma5", "ma5[近5日](元)"),
    ("ma10", "ma10[近5日](元)"),
    ("ma20", "ma20[近5日](元)"),
    ("ma60", "ma60[近5日](元)"),
    ("macd", "macd[近5日]"),
    ("dif", "diff[近5日]"),
    ("dea", "dea[近5日]"),
    ("kdj", "kdj[近5日]"),
    ("kdj_k", "kdj_k值[近5日]"),
    ("kdj_d", "kdj_d值[近5日]"),
    ("kdj_j", "kdj_j值[近5日]"),
    ("rsi6", "rsi6[近5日]"),
    ("rsi12", "rsi12[近5日]"),
    ("rsi24", "rsi24[近5日]"),
    ("boll_mid", "boll_mid[近5日]"),
    ("boll_lower", "boll_lower[近5日]"),
    ("boll_upper", "boll_upper[近5日]"),
    ("obv", "obv[近5日]"),
    ("province", "省份"),
    ("city", "城市"),
    ("concepts", "所属概念"),
    ("index_class", "所属指数类"),
    ("market_type", "股票市场类型"),
    ("main_net_5d_yi", "主力净流入_亿元"),
    ("amount_5d_yi", "成交额_亿元"),
    ("total_mv_yi", "总市值_亿元"),
    ("revenue_yoy_abs", "营收同比_绝对值"),
    ("profit_yoy_abs", "归母同比_绝对值"),
    ("warnings", "风控提示"),
]


# ============ 行业列表加载线程 ============
class LoadIndustriesWorker(QThread):
    finished_signal = Signal(dict)

    def __init__(self, force_refresh: bool = False, parent=None):
        super().__init__(parent)
        self.force_refresh = force_refresh

    def run(self):
        try:
            if not self.force_refresh:
                cached = load_industry_tree()
                if cached:
                    self.finished_signal.emit(cached)
                    return
            rows_by_code = load_market_rows(PREFIXES, START, END)
            tree = build_industry_tree(rows_by_code)
            if tree and tree.get("l1"):
                save_industry_tree(tree)
            self.finished_signal.emit(tree)
        except Exception:
            self.finished_signal.emit({})


# ============ 过滤条件面板 ============
class FilterPanel(QFrame):
    """通用过滤条件：板块/基本面/技术面/资金/估值/行业等 20+ 项"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("QFrame{background:#fafafa;border:1px solid #ddd;}")
        self._tree: Dict[str, Any] = {}
        self._l2_map: Dict[str, Any] = {}
        self._l3_map: Dict[str, Any] = {}
        self._rebuilding = False
        self._build()

    def _add_range(self, layout, row, col, label, min_edit, max_edit):
        layout.addWidget(QLabel(label), row, col * 3)
        layout.addWidget(min_edit, row, col * 3 + 1)
        layout.addWidget(QLabel("-"), row, col * 3 + 2)
        layout.addWidget(max_edit, row, col * 3 + 3)
        for edit in (min_edit, max_edit):
            edit.setFixedWidth(70)
            edit.setPlaceholderText("不限")

    def _build(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(260)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(8)
        layout.setContentsMargins(6, 6, 6, 6)

        # ---- 市场板块 ----
        board_box = QGroupBox("市场板块")
        board_layout = QHBoxLayout(board_box)
        self.cb_main = QCheckBox("主板")
        self.cb_gem = QCheckBox("创业板")
        self.cb_star = QCheckBox("科创板")
        self.cb_bse = QCheckBox("北交所")
        # 默认仅勾选主板，其余板块需手动勾选
        self.cb_main.setChecked(True)
        for cb in (self.cb_main, self.cb_gem, self.cb_star, self.cb_bse):
            board_layout.addWidget(cb)
        board_layout.addStretch()
        layout.addWidget(board_box)

        # ---- 基本条件 ----
        basic_box = QGroupBox("基本条件")
        basic_layout = QGridLayout(basic_box)
        self.cb_non_st = QCheckBox("非ST")
        self.cb_non_st.setChecked(True)
        self.cb_rev_yoy = QCheckBox("营收同比>0")
        self.cb_profit_yoy = QCheckBox("归母净利同比>0")
        self.cb_main_flow = QCheckBox("主力净流入>0(最新日)")
        self.cb_close_ma20 = QCheckBox("收盘价>MA20")
        self.cb_ma20_ma60 = QCheckBox("MA20>MA60")
        self.cb_close_ma60 = QCheckBox("收盘价>MA60")
        self.cb_macd = QCheckBox("MACD>0")
        self.cb_cash_flow = QCheckBox("经营现金流>0")
        self.cb_break_high20 = QCheckBox("突破20日高点")
        self.cb_limit_up = QCheckBox("近5日有涨停")
        basic_cbs = [
            self.cb_non_st, self.cb_rev_yoy, self.cb_profit_yoy,
            self.cb_main_flow, self.cb_close_ma20, self.cb_ma20_ma60,
            self.cb_close_ma60, self.cb_macd, self.cb_cash_flow,
            self.cb_break_high20, self.cb_limit_up,
        ]
        for i, cb in enumerate(basic_cbs):
            basic_layout.addWidget(cb, i // 4, i % 4)
        layout.addWidget(basic_box)

        # ---- 数值范围 ----
        range_box = QGroupBox("数值范围（最小-最大，空表示不限制）")
        range_layout = QGridLayout(range_box)
        range_layout.setColumnStretch(4, 1)

        def make_edits():
            return QLineEdit(), QLineEdit()

        self.le_price_min, self.le_price_max = make_edits()
        self._add_range(range_layout, 0, 0, "股价", self.le_price_min, self.le_price_max)
        self.le_mc_min, self.le_mc_max = make_edits()
        self._add_range(range_layout, 0, 1, "市值(亿)", self.le_mc_min, self.le_mc_max)

        self.le_turn_min, self.le_turn_max = make_edits()
        self._add_range(range_layout, 1, 0, "换手(%)", self.le_turn_min, self.le_turn_max)
        self.le_amount_min, self.le_amount_max = make_edits()
        self._add_range(range_layout, 1, 1, "成交额(亿)", self.le_amount_min, self.le_amount_max)

        self.le_vr_min, self.le_vr_max = make_edits()
        self._add_range(range_layout, 2, 0, "量比", self.le_vr_min, self.le_vr_max)
        self.le_pe_min, self.le_pe_max = make_edits()
        self._add_range(range_layout, 2, 1, "PE", self.le_pe_min, self.le_pe_max)

        self.le_pb_min, self.le_pb_max = make_edits()
        self._add_range(range_layout, 3, 0, "PB", self.le_pb_min, self.le_pb_max)
        self.le_roe_min, self.le_roe_max = make_edits()
        self._add_range(range_layout, 3, 1, "ROE(%)", self.le_roe_min, self.le_roe_max)

        self.le_debt_max = QLineEdit()
        self.le_debt_max.setFixedWidth(70)
        self.le_debt_max.setPlaceholderText("不限")
        range_layout.addWidget(QLabel("负债率上限(%)"), 4, 0)
        range_layout.addWidget(self.le_debt_max, 4, 1)

        self.le_pct_min, self.le_pct_max = make_edits()
        self._add_range(range_layout, 4, 1, "涨幅(%)", self.le_pct_min, self.le_pct_max)

        self.le_rsi_min, self.le_rsi_max = make_edits()
        self._add_range(range_layout, 5, 0, "RSI6", self.le_rsi_min, self.le_rsi_max)
        self.le_dy_min = QLineEdit()
        self.le_dy_min.setFixedWidth(70)
        self.le_dy_min.setPlaceholderText("不限")
        range_layout.addWidget(QLabel("股息率下限(%)"), 5, 3)
        range_layout.addWidget(self.le_dy_min, 5, 4)
        layout.addWidget(range_box)

        # ---- 行业（三级联动） + 概念板块 ----
        industry_box = QGroupBox("行业 / 概念")
        industry_grid = QGridLayout(industry_box)
        industry_grid.setHorizontalSpacing(8)
        industry_grid.setVerticalSpacing(6)

        def make_board_combo(width: int = 140):
            combo = QComboBox()
            combo.addItem("全部")
            combo.setMinimumWidth(width)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return combo

        self.combo_l1 = make_board_combo()
        self.combo_l2 = make_board_combo()
        self.combo_l3 = make_board_combo()
        # 概念板块支持输入搜索（几千个概念）
        self.combo_concept = make_board_combo(200)
        self.combo_concept.setEditable(True)
        self.combo_concept.lineEdit().setPlaceholderText("全部（可输入搜索）")
        # 三级联动信号
        self.combo_l1.currentIndexChanged.connect(self._on_l1_changed)
        self.combo_l2.currentIndexChanged.connect(self._on_l2_changed)

        self.label_industry_status = QLabel("行业加载中...")
        self.label_industry_status.setStyleSheet("color:#999;")
        self.btn_refresh_industry = QPushButton("刷新")
        self.btn_refresh_industry.setToolTip("重新加载行业与概念板块列表")
        self.btn_refresh_industry.setEnabled(False)

        industry_grid.addWidget(QLabel("申万一级:"), 0, 0)
        industry_grid.addWidget(self.combo_l1, 0, 1)
        industry_grid.addWidget(QLabel("申万二级:"), 0, 2)
        industry_grid.addWidget(self.combo_l2, 0, 3)
        industry_grid.addWidget(QLabel("申万三级:"), 0, 4)
        industry_grid.addWidget(self.combo_l3, 0, 5)
        industry_grid.addWidget(QLabel("概念板块:"), 1, 0)
        industry_grid.addWidget(self.combo_concept, 1, 1, 1, 3)
        industry_grid.addWidget(self.label_industry_status, 1, 4)
        industry_grid.addWidget(self.btn_refresh_industry, 1, 5)
        layout.addWidget(industry_box)

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def set_loading(self, loading: bool):
        if loading:
            self.label_industry_status.setText("行业加载中...")
            self.label_industry_status.setStyleSheet("color:#999;")
            self.btn_refresh_industry.setEnabled(False)
        else:
            self.label_industry_status.setText("")
            self.btn_refresh_industry.setEnabled(True)

    def set_industry_tree(self, tree: Dict[str, Any]):
        """填充三级行业联动下拉 + 概念板块下拉。

        tree 结构见 strategy_data.build_industry_tree。
        """
        self._tree = tree
        l1_list = tree.get("l1", [])
        l2_map = tree.get("l2", {})
        l3_map = tree.get("l3", {})
        concepts = tree.get("concepts", [])

        self._rebuilding = True
        try:
            self.combo_l1.clear()
            self.combo_l1.addItem("全部")
            self.combo_l1.addItems(l1_list)

            self.combo_l2.clear()
            self.combo_l2.addItem("全部")
            self.combo_l3.clear()
            self.combo_l3.addItem("全部")

            self.combo_concept.clear()
            self.combo_concept.addItem("全部")
            self.combo_concept.addItems(concepts)
            self.combo_concept.setCurrentIndex(0)
        finally:
            self._rebuilding = False

        self._l2_map = l2_map
        self._l3_map = l3_map
        self.label_industry_status.setText(
            f"一级{len(l1_list)} / 二级{len(l2_map)} / 三级{len(l3_map)} / 概念{len(concepts)}"
        )
        self.label_industry_status.setStyleSheet("color:#28a745;")
        self.btn_refresh_industry.setEnabled(True)

    def _on_l1_changed(self):
        """一级变化 -> 刷新二级、重置三级"""
        if getattr(self, "_rebuilding", False):
            return
        l1 = self.combo_l1.currentText()
        l2_list = self._l2_map.get(l1, []) if l1 != "全部" else []
        self._rebuilding = True
        try:
            self.combo_l2.clear()
            self.combo_l2.addItem("全部")
            self.combo_l2.addItems(sorted(l2_list))
            self.combo_l3.clear()
            self.combo_l3.addItem("全部")
        finally:
            self._rebuilding = False

    def _on_l2_changed(self):
        """二级变化 -> 刷新三级"""
        if getattr(self, "_rebuilding", False):
            return
        l2 = self.combo_l2.currentText()
        l3_list = self._l3_map.get(l2, []) if l2 != "全部" else []
        self._rebuilding = True
        try:
            self.combo_l3.clear()
            self.combo_l3.addItem("全部")
            self.combo_l3.addItems(sorted(l3_list))
        finally:
            self._rebuilding = False

    @staticmethod
    def _parse_float(text: str) -> Optional[float]:
        text = text.strip()
        if not text:
            return None
        try:
            v = float(text)
            return v if v == v else None
        except ValueError:
            return None

    def get_filters(self) -> Dict[str, Any]:
        """收集界面过滤条件为字典"""
        return {
            "boards": {
                "main": self.cb_main.isChecked(),
                "gem": self.cb_gem.isChecked(),
                "star": self.cb_star.isChecked(),
                "bse": self.cb_bse.isChecked(),
            },
            "non_st": self.cb_non_st.isChecked(),
            "revenue_yoy_positive": self.cb_rev_yoy.isChecked(),
            "profit_yoy_positive": self.cb_profit_yoy.isChecked(),
            "main_flow_positive": self.cb_main_flow.isChecked(),
            "close_above_ma20": self.cb_close_ma20.isChecked(),
            "ma20_above_ma60": self.cb_ma20_ma60.isChecked(),
            "close_above_ma60": self.cb_close_ma60.isChecked(),
            "macd_positive": self.cb_macd.isChecked(),
            "cash_flow_positive": self.cb_cash_flow.isChecked(),
            "break_high20": self.cb_break_high20.isChecked(),
            "limit_up_recent": self.cb_limit_up.isChecked(),
            "price_min": self._parse_float(self.le_price_min.text()),
            "price_max": self._parse_float(self.le_price_max.text()),
            "market_cap_min": self._parse_float(self.le_mc_min.text()),
            "market_cap_max": self._parse_float(self.le_mc_max.text()),
            "turnover_min": self._parse_float(self.le_turn_min.text()),
            "turnover_max": self._parse_float(self.le_turn_max.text()),
            "amount_min": self._parse_float(self.le_amount_min.text()) or None,
            "amount_max": self._parse_float(self.le_amount_max.text()) or None,
            "vol_ratio_min": self._parse_float(self.le_vr_min.text()),
            "vol_ratio_max": self._parse_float(self.le_vr_max.text()),
            "pe_min": self._parse_float(self.le_pe_min.text()),
            "pe_max": self._parse_float(self.le_pe_max.text()),
            "pb_min": self._parse_float(self.le_pb_min.text()),
            "pb_max": self._parse_float(self.le_pb_max.text()),
            "roe_min": self._parse_float(self.le_roe_min.text()),
            "roe_max": self._parse_float(self.le_roe_max.text()),
            "debt_max": self._parse_float(self.le_debt_max.text()),
            "pct_chg_min": self._parse_float(self.le_pct_min.text()),
            "pct_chg_max": self._parse_float(self.le_pct_max.text()),
            "rsi_min": self._parse_float(self.le_rsi_min.text()),
            "rsi_max": self._parse_float(self.le_rsi_max.text()),
            "dividend_yield_min": self._parse_float(self.le_dy_min.text()),
            "industry_l1": self.combo_l1.currentText(),
            "industry_l2": self.combo_l2.currentText(),
            "industry_l3": self.combo_l3.currentText(),
            "concept": self.combo_concept.currentText(),
        }


# ============ K线绘制控件 ============
class KLineWidget(QWidget):
    """自绘K线图：K线 + MA5/10/20/60 + 成交量"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[dict] = []
        self.setMinimumHeight(320)
        self.setStyleSheet("background:#ffffff;")

    def set_data(self, rows: List[dict]):
        self.rows = valid_trading_rows(rows)[-120:]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if not self.rows or w <= 0 or h <= 0:
            painter.setPen(QColor("#999"))
            painter.drawText(10, 20, "无数据")
            return

        # 上下分区：K线 70%，成交量 30%
        kline_h = int(h * 0.7)
        vol_h = h - kline_h - 10
        margin = 40  # 左右留白

        closes = [r.get("close", 0) for r in self.rows]
        highs = [r.get("high", 0) for r in self.rows]
        lows = [r.get("low", 0) for r in self.rows]
        vols = [r.get("volume", 0) for r in self.rows]
        max_high = max(highs) if highs else 1
        min_low = min(lows) if lows else 0
        max_vol = max(vols) if vols else 1

        n = len(self.rows)
        candle_w = (w - 2 * margin) / n
        body_w = max(2, candle_w * 0.6)

        # 计算MA
        def ma(p):
            result = []
            for i in range(n):
                if i < p - 1:
                    result.append(None)
                else:
                    result.append(sum(closes[i - p + 1:i + 1]) / p)
            return result

        ma5 = ma(5)
        ma10 = ma(10)
        ma20 = ma(20)
        ma60 = ma(60)

        def x(i): return margin + i * candle_w + candle_w / 2
        def y_price(p): return kline_h - (p - min_low) / (max_high - min_low) * (kline_h - 20) - 10
        def y_vol(v): return kline_h + 5 + (1 - v / max_vol) * (vol_h - 10)

        # 画K线
        for i, row in enumerate(self.rows):
            o, c = row.get("open", 0), row.get("close", 0)
            h_, l_ = row.get("high", 0), row.get("low", 0)
            color = QColor("#e53935") if c >= o else QColor("#1e88e5")
            pen = QPen(color, 1)
            painter.setPen(pen)
            # 影线
            painter.drawLine(int(x(i)), int(y_price(h_)), int(x(i)), int(y_price(l_)))
            # 实体
            top = min(y_price(o), y_price(c))
            body_h = max(1, abs(y_price(o) - y_price(c)))
            painter.setBrush(color)
            painter.drawRect(int(x(i) - body_w / 2), int(top), int(body_w), int(body_h))
            # 成交量
            v = row.get("volume", 0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRect(int(x(i) - body_w / 2), int(y_vol(v)), int(body_w), int(vol_h - (y_vol(v) - kline_h - 5)))

        # 画MA线
        def draw_ma(series, color):
            if not series:
                return
            pen = QPen(QColor(color), 1)
            painter.setPen(pen)
            points = []
            for i, v in enumerate(series):
                if v is not None:
                    points.append((x(i), y_price(v)))
            for i in range(1, len(points)):
                painter.drawLine(int(points[i-1][0]), int(points[i-1][1]),
                                 int(points[i][0]), int(points[i][1]))

        draw_ma(ma5, "#f57c00")
        draw_ma(ma10, "#8e24aa")
        draw_ma(ma20, "#1e88e5")
        draw_ma(ma60, "#43a047")

        # 标题
        painter.setPen(QColor("#333"))
        font = QFont("Microsoft YaHei", 9)
        painter.setFont(font)
        last = self.rows[-1]
        title = f"{last.get('code','')} {last.get('name','')}  收盘:{last.get('close',0)}  涨幅:{last.get('pct_chg',0)}%"
        painter.drawText(10, 16, title)

        painter.end()


# ============ 结果表格 Model（QTableView 数据驱动，几千行流畅渲染） ============
class ResultTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.results: List[dict] = []

    def set_results(self, results: List[dict]):
        self.beginResetModel()
        self.results = results or []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.results)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(RESULT_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return RESULT_COLUMNS[section][1]
        return section + 1

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self.results[index.row()]
        key = RESULT_COLUMNS[index.column()][0]
        if role == Qt.DisplayRole:
            return self._text(r, key)
        if role == Qt.ForegroundRole:
            return self._color(r, key)
        if role == Qt.UserRole:
            return r
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        key = RESULT_COLUMNS[column][0]

        def sort_key(r):
            if key == "score":
                return r.get("score", 0)
            if key == "code":
                return r.get("code", "")
            if key == "name":
                return r.get("name", "")
            v = (r.get("full") or {}).get(key)
            try:
                return float(v)
            except (TypeError, ValueError):
                return -1e18 if isinstance(v, str) else (v if v is not None else -1e18)

        self.layoutAboutToBeChanged.emit()
        self.results.sort(key=sort_key, reverse=(order == Qt.DescendingOrder))
        self.layoutChanged.emit()

    @staticmethod
    def _text(r: dict, key: str) -> str:
        full = r.get("full") or {}
        if key == "score":
            return f'{r.get("score", 0):.1f}'
        if key == "warnings":
            return "; ".join(r["warnings"]) if r.get("warnings") else ""
        return ResultTableModel._fmt(full.get(key))

    @staticmethod
    def _fmt(v, nd: int = 2) -> str:
        if v is None:
            return "-"
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        if f != f:
            return "-"
        if abs(f) >= 1e9:
            return f"{f:,.2f}"
        return f"{f:,.{nd}f}"

    @staticmethod
    def _color(r: dict, key: str):
        full = r.get("full") or {}
        # 未命中策略：整行绿色（不合格）
        if not r.get("passed", True):
            return QColor("#4caf50")
        if key == "score":
            s = r.get("score", 0)
            return QColor("#e53935") if s >= 70 else QColor("#f57c00") if s >= 60 else QColor("#757575")
        if key == "leader_tag":
            return QColor("#d32f2f")
        if key == "yaogu_tag":
            v = full.get("yaogu_tag") or ""
            if v.startswith("强"):
                return QColor("#e53935")
            if v == "妖股气质":
                return QColor("#f57c00")
        if key == "pct_chg":
            p = full.get("pct_chg")
            if p is not None:
                return QColor("#e53935") if p >= 0 else QColor("#1e88e5")
        if key in ("revenue_yoy", "profit_yoy", "revenue_yoy_abs", "profit_yoy_abs"):
            v = full.get(key)
            if v is not None:
                return QColor("#e53935") if v >= 0 else QColor("#1e88e5")
        return None


# ============ 详情弹窗（K线 + 因子评分），点击表格行才弹出 ============
class DetailWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("个股详情")
        self.resize(760, 720)
        layout = QVBoxLayout(self)
        self.kline_widget = KLineWidget()
        self.kline_widget.setMinimumHeight(360)
        layout.addWidget(self.kline_widget, stretch=3)
        self.factor_label = QLabel("点击股票查看详情")
        self.factor_label.setWordWrap(True)
        self.factor_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.factor_label.setStyleSheet("padding:8px;background:#f5f5f5;")
        layout.addWidget(self.factor_label, stretch=2)

    def show_result(self, r: dict, kline_cache: Dict[str, List[dict]]):
        code = r.get("code", "")
        name = r.get("name", "")
        self.setWindowTitle(f"个股详情 - {code} {name}")
        rows = kline_cache.get(code)
        if rows:
            self.kline_widget.set_data(rows)
        else:
            self.kline_widget.set_data([])
        self.factor_label.setText(self._build_text(r))

    @staticmethod
    def _build_text(r: dict) -> str:
        lines = [
            f"综合分: {r.get('score', 0):.1f}",
            f"命中策略: {'是(红色)' if r.get('passed') else '否(绿色)'}",
            "风控提示: " + ("; ".join(r.get("warnings")) if r.get("warnings") else "无"),
        ]
        fs = r.get("factor_scores") or {}
        if fs:
            lines.append("\n-- 14因子评分 --")
            factor_names = {f["key"]: f["name"] for f in FACTORS}
            for f_key, f_val in fs.items():
                lines.append(f"  {factor_names.get(f_key, f_key)}: {f_val}")
        det = r.get("details") or {}
        if det:
            lines.append("\n-- 核心指标 --")
            for k, v in det.items():
                if v is not None:
                    lines.append(f"  {k}: {v}")
        return "\n".join(lines)


# ============ 主窗口 ============
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("v9 股票策略扫描系统")
        self.resize(1280, 900)
        self.results: List[dict] = []
        self.worker: Optional[ScanWorker] = None
        self.kline_cache: Dict[str, List[dict]] = {}
        self.industry_worker: Optional[LoadIndustriesWorker] = None

        self._build_ui()
        self._connect()
        self._load_industries()

    def _build_ui(self):
        # 三大页面：实时扫描 / 策略管理（迭代） / 回测管理（验证）
        central = QTabWidget()
        self.setCentralWidget(central)
        self.tabs = central
        scan_page = QWidget()
        layout = QVBoxLayout(scan_page)
        central.addTab(scan_page, "实时扫描")

        # ---- 顶部控制栏 ----
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("策略:"))
        self.strategy_combo = QComboBox()
        for s in get_strategies():
            self.strategy_combo.addItem(s["name"], s["key"])
        top_bar.addWidget(self.strategy_combo)

        self.scan_btn = QPushButton("开始全量扫描")
        top_bar.addWidget(self.scan_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        top_bar.addWidget(self.stop_btn)
        self.export_btn = QPushButton("导出Excel")
        self.export_btn.setEnabled(False)
        top_bar.addWidget(self.export_btn)

        top_bar.addStretch()
        self.status_label = QLabel("就绪")
        top_bar.addWidget(self.status_label)
        layout.addLayout(top_bar)

        # ---- 过滤条件面板（可折叠，默认展开） ----
        self.filter_toggle_btn = QPushButton("▾ 筛选条件（点击折叠/展开）")
        self.filter_toggle_btn.setCheckable(True)
        self.filter_toggle_btn.setChecked(True)
        self.filter_toggle_btn.clicked.connect(self._toggle_filter)
        layout.addWidget(self.filter_toggle_btn)
        self.filter_panel = FilterPanel()
        layout.addWidget(self.filter_panel)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ---- 综合分快速过滤（读因子索引快照，秒级，不重算） ----
        quick_bar = QHBoxLayout()
        quick_bar.addWidget(QLabel("综合分 ≥"))
        self.le_score_min = QLineEdit("70")
        self.le_score_min.setFixedWidth(60)
        self.le_score_min.setToolTip(
            "从上次扫描落库的因子索引中按综合分直接过滤（秒级，无需重算）。\n"
            "因子索引按综合分作为键存储，查询直接在服务端按分数区间筛选。\n"
            "盘中如需结合实时盘口重算，请点“开始全量扫描”。")
        quick_bar.addWidget(self.le_score_min)
        self.quick_btn = QPushButton("快速过滤（读快照）")
        self.quick_btn.clicked.connect(self.quick_filter)
        quick_bar.addWidget(self.quick_btn)
        self.quick_hint = QLabel("")
        self.quick_hint.setStyleSheet("color: #888;")
        quick_bar.addWidget(self.quick_hint)
        quick_bar.addStretch()
        layout.addLayout(quick_bar)

        # ---- 结果表格（QTableView + 数据模型，几千行流畅渲染） ----
        self.table = QTableView()
        self.table_model = ResultTableModel(self.table)
        self.table.setModel(self.table_model)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(110)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table, stretch=1)

        # ---- 底部汇总 ----
        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        # ---- 策略管理（迭代） + 回测管理（验证） ----
        self.strategy_page = StrategyPage()
        central.addTab(self.strategy_page, "策略管理")
        self.backtest_page = BacktestPage()
        # 回测直接读取策略页未保存的编辑态，实现「改完立即验证」
        self.backtest_page.strategy_provider = self.strategy_page.current_config
        central.addTab(self.backtest_page, "回测管理")

    def _toggle_filter(self):
        show = self.filter_toggle_btn.isChecked()
        self.filter_panel.setVisible(show)
        self.filter_toggle_btn.setText(
            "▾ 筛选条件（点击折叠/展开）" if show else "▸ 筛选条件（已折叠，点击展开）"
        )

    def quick_filter(self):
        """组合过滤（读上次扫描快照，秒级，不重算）。

        - 综合分下限 + FilterPanel 全部过滤条件，对落库的因子宽表逐条重放
        - 数据来源分层：本地历史(L)直接复用；在线接口(O)超时标 stale；
          盘中实时(R)标 realtime 提示重算
        """
        try:
            lo = float(self.le_score_min.text().strip())
        except ValueError:
            QMessageBox.warning(self, "提示", "请输入有效的最低综合分（0-100）")
            return
        lo = max(0.0, min(100.0, lo))
        self.quick_btn.setEnabled(False)
        self.quick_hint.setText("正在组合过滤...")
        try:
            filters = self.filter_panel.get_filters() if hasattr(self.filter_panel, "get_filters") else None
            results = filter_factor_table(filters, min_score=lo, end=END, limit=2000)
            if not results:
                self.quick_hint.setText("无匹配：请先全量扫描落库，或放宽条件")
                return
            fr = factor_freshness(results[0])
            hint = f"综合分≥{lo:g} 命中{len(results)}只（快照{END}"
            if fr.get("ts"):
                from datetime import datetime as _dt
                hint += f" 扫描于{_dt.fromtimestamp(fr['ts']):%m-%d %H:%M}"
            if fr.get("has_stale"):
                hint += " ⚠接口因子超期"
            if fr.get("has_realtime"):
                hint += " ⚠盘口因子为代理值"
            hint += "，未重算）"
            self.results = results
            self.table_model.set_results(results)
            self.export_btn.setEnabled(bool(results))
            self.update_summary()
            self.quick_hint.setText(hint)
        except Exception as e:
            self.quick_hint.setText("查询失败")
            QMessageBox.critical(self, "错误", str(e))
        finally:
            self.quick_btn.setEnabled(True)

    def _connect(self):
        self.scan_btn.clicked.connect(self.start_scan)
        self.stop_btn.clicked.connect(self.stop_scan)
        self.export_btn.clicked.connect(self.export_excel)
        self.table.selectionModel().selectionChanged.connect(self.on_select)
        self.filter_panel.btn_refresh_industry.clicked.connect(
            lambda: self._load_industries(force_refresh=True)
        )

    def _load_industries(self, force_refresh: bool = False):
        self.filter_panel.set_loading(True)
        self.status_label.setText("正在加载行业列表...")
        if self.industry_worker and self.industry_worker.isRunning():
            self.industry_worker.wait(1000)
        self.industry_worker = LoadIndustriesWorker(force_refresh=force_refresh)
        self.industry_worker.finished_signal.connect(self._on_industries_loaded)
        self.industry_worker.start()

    def _on_industries_loaded(self, tree):
        if isinstance(tree, dict) and tree.get("l1"):
            self.filter_panel.set_industry_tree(tree)
            self.status_label.setText(
                f"行业/概念加载完成，就绪"
            )
        else:
            self.filter_panel.set_loading(False)
            self.status_label.setText("行业列表加载失败，可点击刷新重试")

    def start_scan(self):
        if self.worker and self.worker.isRunning():
            return
        strategy_key = self.strategy_combo.currentData()
        filters = self.filter_panel.get_filters()
        self.results = []
        self.table_model.set_results([])
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.worker = ScanWorker(
            strategy_key, filters=filters,
            strategy_config=self.strategy_page.current_config())
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_signal.connect(self.on_scan_done)
        self.worker.error_signal.connect(self.on_error)
        self.worker.start()

    def stop_scan(self):
        if self.worker:
            self.worker.stop()
            self.status_label.setText("正在停止...")

    def on_progress(self, percent, msg):
        self.progress_bar.setValue(percent)
        self.status_label.setText(msg)

    def on_scan_done(self, results):
        self.results = results
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.export_btn.setEnabled(bool(results))
        self.populate_table()
        self.update_summary()
        # 回测页默认标的池 = 本次扫描命中池
        self.backtest_page.set_hits_codes(
            [r["code"] for r in results if r.get("passed")])

    def on_error(self, msg):
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        QMessageBox.critical(self, "错误", f"扫描失败: {msg}")

    def populate_table(self):
        # 结果已在扫描线程排好序（命中在前、按综合分倒序），直接展示
        self.table_model.set_results(self.results)

    def export_excel(self):
        if not self.results:
            QMessageBox.information(self, "提示", "没有可导出的数据")
            return
        default_name = f"scan_result_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出Excel", default_name, "Excel文件 (*.xlsx)"
        )
        if not path:
            return
        try:
            import pandas as pd
            headers = [h for _, h in RESULT_COLUMNS]
            data = []
            for r in self.results:
                full = r.get("full") or {}
                row = []
                for key, _h in RESULT_COLUMNS:
                    if key == "score":
                        row.append(r["score"])
                    elif key == "warnings":
                        row.append("; ".join(r["warnings"]))
                    else:
                        row.append(full.get(key))
                data.append(row)
            df = pd.DataFrame(data, columns=headers)
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="扫描结果")
                ws = writer.sheets["扫描结果"]
                ws.freeze_panes = "D2"
                widths = {}
                for i, h in enumerate(headers, 1):
                    col = ws.cell(row=1, column=i).column_letter
                    ws.column_dimensions[col].width = max(
                        len(h) * 1.6 + 4,
                        widths.get(col, 12),
                    )
            QMessageBox.information(
                self, "导出成功", f"已导出 {len(data)} 条到:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def update_summary(self):
        if not self.results:
            self.summary_label.setText("无结果")
            return
        passed = sum(1 for r in self.results if r.get("passed"))
        strong = sum(1 for r in self.results if r.get("passed") and r["score"] >= 70)
        self.summary_label.setText(
            f"共 {len(self.results)} 只 | 命中策略 {passed} 只（红色，其中高分≥70: {strong}） | "
            f"未命中 {len(self.results) - passed} 只（绿色）"
        )

    def on_select(self, selected=None, deselected=None):
        idx = self.table.currentIndex()
        if not idx.isValid():
            return
        r = idx.data(Qt.UserRole)
        if not r:
            return
        code = r.get("code", "")
        # 加载K线（缓存）
        if code and code not in self.kline_cache:
            try:
                all_rows = load_market_rows([f"{code[0]}*"], START, END)
                self.kline_cache[code] = all_rows.get(code, [])
            except Exception:
                self.kline_cache[code] = []
        if not hasattr(self, "_detail_win") or self._detail_win is None:
            self._detail_win = DetailWindow()
        self._detail_win.show_result(r, self.kline_cache)
        self._detail_win.show()
        self._detail_win.raise_()
        self._detail_win.activateWindow()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
