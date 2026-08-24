# -*- coding: utf-8 -*-
"""
本地历史回测引擎。

核心思路：
    - 只依赖「本地历史」数据（日K + 自算指标），天然无前视偏差；
    - 对每只股票一次性预计算全序列指标（IndicatorSeries），
      回测时按交易日 O(1) 取用；
    - 打分与实时扫描共用 strategy_schema 规则引擎，
      策略在界面上的迭代调整会直接反映到回测结果。

数据源感知：
    - 可回测因子 = 来源 L 且 backtestable=True（排除板块/题材/市场环境，
      它们没有历史回放数据）；
    - O（在线）/ R（实时盘口）因子在回测中不可用，报告中明确列出，
      避免用户误以为回测覆盖了全因子。
"""
from __future__ import annotations

import bisect
import os
import time
from math import isfinite
from typing import Any, Callable, Dict, List, Optional

from stock_sdk import rd, warm_default_connection, zb

warm_default_connection()

from strategy_data import valid_trading_rows, load_market_rows, A_SHARE_PREFIXES, calc_window_start
from screen_common import (
    DEFAULT_SCAN_FILTERS, evaluate_buy, score_factor_local,
)
from strategy_schema import (
    SRC_LOCAL, SRC_ONLINE, SRC_REALTIME,
    build_factor_defs, build_rules_map,
    score_factor_set, total_score,
    DEFAULT_FACTOR_DEFS,
)
from strategies import check_strategy

# 回测覆盖的本地字段（与 factors.build_factor_ctx 一致）
_CTX_KEYS = [
    "close", "pct", "amount", "turnover", "volume", "amplitude",
    "vol_ratio", "limit_up_5", "is_break", "profit_ratio", "bull_arrange",
    "dev_ma20", "dev_ma60",
    "ma5", "ma10", "ma20", "ma60", "macd", "rsi6", "k", "d",
    "kd_strong", "kd_weak",
    "main_net", "dde_net", "rev_yoy", "profit_yoy", "pe", "pb",
    "board_score", "market_score",
    "order_book_pct", "position_pct",
]


# ============ 全序列指标 ============
class IndicatorSeries:
    """对一只股票的完整历史序列预计算全部指标，支持按日 O(1) 取上下文。"""

    def __init__(self, code: str, rows: List[dict]):
        self.code = code
        self.rows = valid_trading_rows(rows)
        self.n = len(self.rows)
        self.dates: List[str] = []
        if self.n == 0:
            return
        closes = []; pcts = []; amounts = []; turnovers = []
        vols = []; highs = []; lows = []; amplitudes = []
        for r in self.rows:
            self.dates.append(str(r.get("date", "")))
            closes.append(_f(r.get("close")) or 0.0)
            pcts.append(_f(r.get("pct_chg")) or 0.0)
            amounts.append(_f(r.get("amount")) or 0.0)
            turnovers.append(_f(r.get("turnover")) or 0.0)
            vols.append(_f(r.get("volume")) or 0.0)
            highs.append(_f(r.get("high")) or closes[-1])
            lows.append(_f(r.get("low")) or closes[-1])
            amplitudes.append(_f(r.get("amplitude")) or 0.0)
        n = self.n

        # 均线（滑动窗口）
        ma5 = _sma(closes, 5); ma10 = _sma(closes, 10)
        ma20 = _sma(closes, 20); ma60 = _sma(closes, 60)

        # MACD（EMA 递推）
        macd = _macd(closes)

        # RSI6（Wilder 递推）
        rsi6 = _rsi(closes, 6)

        # KDJ（RSV9 递推）
        k_arr, d_arr = _kdj(highs, lows, closes)

        # 滚动极值
        high20 = _rolling_max(highs, 20)
        high60 = _rolling_max(highs, 60)
        low60 = _rolling_min(lows, 60)

        # 量比：今日量 / 前5日均量
        vol_ratio = [1.0] * n
        for i in range(5, n):
            avg5 = sum(vols[i - 5:i]) / 5.0
            vol_ratio[i] = vols[i] / avg5 if avg5 > 0 else 1.0

        # 近5日涨停数
        limit_up = [0] * n
        for i in range(n):
            lo = max(0, i - 4)
            limit_up[i] = sum(1 for j in range(lo, i + 1) if pcts[j] >= 9.5)

        is_break = [False] * n
        profit_ratio = [0.5] * n
        for i in range(n):
            h20 = high20[i]
            is_break[i] = closes[i] >= h20 * 0.995
            if high60[i] > low60[i]:
                profit_ratio[i] = (closes[i] - low60[i]) / (high60[i] - low60[i])

        dev_ma20 = [_safe_div(c, m) - 1 if m else None for c, m in zip(closes, ma20)]
        dev_ma60 = [_safe_div(c, m) - 1 if m else None for c, m in zip(closes, ma60)]
        bull = [_b(m5, m10, m20, m60) for m5, m10, m20, m60 in zip(ma5, ma10, ma20, ma60)]
        kd_strong = [bool(k is not None and d_ is not None and k > d_ and k > 50)
                     for k, d_ in zip(k_arr, d_arr)]
        kd_weak = [bool(k is not None and d_ is not None and k < d_)
                   for k, d_ in zip(k_arr, d_arr)]

        self._data = {
            "close": closes, "pct": pcts, "amount": amounts,
            "turnover": turnovers, "volume": vols, "amplitude": amplitudes,
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
            "macd": macd, "rsi6": rsi6, "k": k_arr, "d": d_arr,
            "vol_ratio": vol_ratio, "limit_up_5": limit_up,
            "is_break": is_break, "profit_ratio": profit_ratio,
            "dev_ma20": dev_ma20, "dev_ma60": dev_ma60,
            "bull_arrange": bull, "kd_strong": kd_strong, "kd_weak": kd_weak,
            "high20": high20,
        }
        self.idx_by_date = {d: i for i, d in enumerate(self.dates)}

    @staticmethod
    def _norm_date(date) -> str:
        """日期归一化为 'YYYYMMDD' 字符串。

        行情行 date 字段可能是 int（20260821）或 str（'20260821'），
        idx_by_date 的 key 恒为 str；统一归一化避免 has_date 恒 False
        导致扫描端整池 0 命中（回测端 axis 已为 str，不受影响）。
        """
        return str(date)

    def has_date(self, date) -> bool:
        return self._norm_date(date) in self.idx_by_date

    def index_at(self, date) -> int:
        """最近 <= date 的索引；无则 -1。"""
        i = bisect.bisect_right(self.dates, self._norm_date(date)) - 1
        return i

    def ctx_at(self, date, exact: bool = False) -> Optional[Dict[str, Any]]:
        """构造该日的规则引擎上下文；exact=True 时停牌日返回 None。"""
        date = self._norm_date(date)
        i = self.index_at(date)
        if i < 0:
            return None
        if exact and self.dates[i] != date:
            return None
        d = self._data
        ctx = {
            "close": d["close"][i], "pct": d["pct"][i],
            "amount": d["amount"][i], "turnover": d["turnover"][i],
            "volume": d["volume"][i], "amplitude": d["amplitude"][i],
            "vol_ratio": d["vol_ratio"][i], "limit_up_5": d["limit_up_5"][i],
            "is_break": d["is_break"][i], "profit_ratio": d["profit_ratio"][i],
            "bull_arrange": d["bull_arrange"][i],
            "dev_ma20": d["dev_ma20"][i], "dev_ma60": d["dev_ma60"][i],
            "ma5": d["ma5"][i], "ma10": d["ma10"][i],
            "ma20": d["ma20"][i], "ma60": d["ma60"][i],
            "macd": d["macd"][i], "rsi6": d["rsi6"][i],
            "k": d["k"][i], "d": d["d"][i],
            "kd_strong": d["kd_strong"][i], "kd_weak": d["kd_weak"][i],
            "board_score": 0.0, "market_score": 0.0,
            "main_net": 0.0, "dde_net": 0.0, "rev_yoy": 0.0,
            "profit_yoy": 0.0, "pe": None, "pb": None,
            "order_book_pct": d["pct"][i], "position_pct": d["pct"][i],
        }
        return ctx

    def indicator_at(self, date) -> Dict[str, Any]:
        """给 strategies.check_strategy 用的指标字典。"""
        i = self.index_at(self._norm_date(date))
        if i < 0:
            return {}
        d = self._data
        return {"ma5": d["ma5"][i], "ma10": d["ma10"][i],
                "ma20": d["ma20"][i], "ma60": d["ma60"][i],
                "macd": d["macd"][i], "rsi6": d["rsi6"][i],
                "k": d["k"][i], "d": d["d"][i], "close": d["close"][i],
                "vol_ratio": d["vol_ratio"][i], "high20": d["high20"][i]}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
        return x if isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _safe_div(a: float, b: float) -> Optional[float]:
    return a / b if b else None


def _sma(vals: List[float], win: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= win:
            s -= vals[i - win]
        if i >= win - 1:
            out[i] = s / win
    return out


def _macd(closes: List[float]) -> List[Optional[float]]:
    n = len(closes)
    ema12 = [0.0] * n; ema26 = [0.0] * n
    dif = [0.0] * n
    for i, c in enumerate(closes):
        ema12[i] = ema12[i - 1] * 11 / 13 + c * 2 / 13 if i else c
        ema26[i] = ema26[i - 1] * 25 / 27 + c * 2 / 27 if i else c
        dif[i] = ema12[i] - ema26[i]
    dea = [0.0] * n
    for i in range(n):
        dea[i] = dea[i - 1] * 8 / 10 + dif[i] * 2 / 10 if i else dif[i]
    return [d - e for d, e in zip(dif, dea)]


def _rsi(closes: List[float], period: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out
    gains = [0.0] * n; losses = [0.0] * n
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        if ch > 0:
            gains[i] = ch
        else:
            losses[i] = -ch
    avg_g = sum(gains[1:period + 1]) / period
    avg_l = sum(losses[1:period + 1]) / period
    out[period] = _rsi_val(avg_g, avg_l)
    for i in range(period + 1, n):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        out[i] = _rsi_val(avg_g, avg_l)
    return out


def _rsi_val(avg_g: float, avg_l: float) -> Optional[float]:
    if avg_g + avg_l == 0:
        return None
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def judge_at(s: "IndicatorSeries", date: str, filters: Dict[str, Any],
             market_ok: bool, max_buy_pct: Optional[float], min_score: float,
             defs_full: List[dict], rules_map: Optional[Dict[str, List[dict]]] = None,
             use_factor: bool = True, strategy_key: str = "factor_default",
             online: Optional[Dict[str, Any]] = None,
             return_fail: bool = False) -> Optional[Dict[str, Any]]:
    """两端共用的单股买入判定（回测调仓日 / 扫描当日走同一函数）。

    流程与回测/扫描两端的原内联逻辑逐字对齐：
      1. 当日必须有数据（等价 has_date）；
      2. 近5行 recent + 本地指标 ind（IndicatorSeries 自算）；
      3. score_factor_local 本地可回测综合分（环境/在线字段置 0）；
      4. use_factor：综合分 >= min_score 命中；v9：check_strategy 硬条件命中；
      5. evaluate_buy 统一判定（过滤链 + 策略命中 + 不追高）。

    返回 {"scored", "verdict", "recent", "ind"}。
    return_fail=False（回测买入段默认）：判定不通过返回 None（不买入）。
    return_fail=True（扫描端展示用）：判定不通过也返回 verdict（ok=False），
    由调用方按 passed/limit_ok 标记绿/灰色展示，避免大盘过滤不通过时
    结果表整体为空（0 命中）。
    判定口径与在线数据解耦（online 固定传回测口径），保证两端严格一致。
    """
    if not s.has_date(date):
        return None
    i = s.index_at(date)
    if i < 0:
        return None
    recent = s.rows[max(0, i - 4):i + 1]
    ind = s.indicator_at(date)
    if not ind:
        return None
    scored = score_factor_local(defs_full, recent, ind, rules_map)
    if use_factor:
        strat_hit = scored["total"] >= min_score
    else:
        strat_hit = check_strategy(strategy_key, s.rows[:i + 1], {}, ind)
    verdict = evaluate_buy(s.code, recent, ind, online or {}, filters, market_ok,
                           max_buy_pct, strat_hit=strat_hit, score=scored["total"])
    if not verdict["ok"] and not return_fail:
        return None
    return {"scored": scored, "verdict": verdict, "recent": recent, "ind": ind}


def _market_rsi(vals: List[Optional[float]], period: int = 14,
                end: Optional[int] = None) -> Optional[float]:
    """市场指数简单平均 RSI（period 日，返回当日标量）。

    与扫描端共用同一实现，保证两端一致。数据不足 period+1 个点时
    返回 None（调用方视为放行）。注意：与股票的 ``_rsi``（数组版）
    不同名，避免覆盖。
    """
    n = len(vals) if end is None else min(end + 1, len(vals))
    if n < period + 1:
        return None
    gains = losses = 0.0
    for i in range(n - period, n):
        ch = (vals[i] or 0.0) - (vals[i - 1] or 0.0)
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    avg_g = gains / period
    avg_l = losses / period
    if avg_l == 0.0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def _market_ok(market_close, market_ma20, di: int, enabled: bool = True,
               mode: str = "strong", up_days: int = 3,
               rsi_threshold: float = 40.0,
               chg20_max: Optional[float] = None,
               chg20_max2: Optional[float] = None,
               chg60_min: Optional[float] = None) -> bool:
    """大盘过滤：全池等权指数的技术状态决定是否允许买入。

    mode="above"：仅要求指数 >= 20 日线（原版弱过滤）；
    mode="strong"：额外要求 20 日线处于上行（当前值高于 up_days 个
    交易日前的值），即「指数在 20 日线上方 + 20 日线走多」；
    mode="oversold"：指数 RSI14 < rsi_threshold 时放行（超卖反弹
    入场窗口；均值回归市场下，追涨过滤在统计上是反向的，超卖入场
    的前向收益显著为正）。

    chg20_max：oversold 模式下的"深度超卖"主条件（可为 None 关闭）。
    要求大盘 20 日涨幅低于该阈值（例如 -14.0 表示近 20 日已跌超 14%），
    过滤"浅超卖/假超卖"（RSI 低位但大盘并未深跌，前向收益差）。

    chg20_max2 + chg60_min：oversold 模式下的次条件「牛市回调超卖」。
    当主条件未满足（跌幅不够深）时，若 20 日跌幅达到 chg20_max2（较浅）
    且 60 日趋势仍向上（chg60 > chg60_min），同样放行——用于区分
    「上升趋势中的急跌回调」（V 型反转，如 2026-03）与「下降趋势中的
    阴跌」（绞肉机，如 2026-06/2024 年初）。两者均可为 None 关闭。

    enabled=False 或数据不足/缺失时视为通过（其余模式）或跳过（oversold）。
    """
    if not enabled:
        return True
    if mode == "oversold":
        # 超卖模式是「准入条件」：无法确认超卖状态时一律跳过买入，
        # 而不是放行——否则回测窗口起始段（无大盘历史）会把浅跌
        # 误判为深度超卖无脑买入（2024年初阴跌陷阱的教训）。
        if di >= len(market_close):
            return False
        mc = market_close[di]
        if mc is None:
            return False
        r = _market_rsi(market_close, 14, di)
        if r is None:
            return False
        if r >= rsi_threshold:
            return False
        if chg20_max is None:
            return True
        if di < 20 or market_close[di - 20] is None:
            return False
        chg20 = (mc / market_close[di - 20] - 1.0) * 100.0
        if chg20 < chg20_max:
            return True
        # 主条件未满足：尝试「牛市回调超卖」次规则
        if chg20_max2 is not None and di >= 60 and market_close[di - 60] is not None:
            if chg20 < chg20_max2:
                chg60 = (mc / market_close[di - 60] - 1.0) * 100.0
                if chg60_min is None or chg60 > chg60_min:
                    return True
        return False
    # 其余模式（above/strong）：沿用"数据缺失视为通过"的旧行为
    if di >= len(market_close):
        return True
    mc = market_close[di]
    if mc is None:
        return True
    if di >= len(market_ma20):
        return True
    mma = market_ma20[di]
    if mma is None:
        return True
    if mc < mma:
        return False
    if mode == "strong":
        j = di - up_days
        if j >= 0:
            prev = market_ma20[j]
            # MA20 横盘/下行不放行；回看数据不足时只要求指数在线上方
            if prev is not None and mma <= prev:
                return False
    return True


def scan_market_ok(rows_by_code: Dict[str, List[dict]], mode: str = "strong",
                   ma_days: int = 20, up_days: int = 3,
                   rsi_threshold: float = 40.0,
                   chg20_max: Optional[float] = None,
                   chg20_max2: Optional[float] = None,
                   chg60_min: Optional[float] = None) -> bool:
    """扫描端大盘过滤：由全池等权指数序列判定当前是否允许买入。

    与回测 ``_market_ok`` 使用同一指数口径（按日期对齐的全池收盘等权、
    当日无数据沿用前值）与同一判定函数，保证两端一致。
    数据不足/接口异常时放行（True），避免误伤。
    """
    try:
        # 与回测一致：全池等权收盘指数（日期对齐，前值填充）
        by_date: Dict[str, List[float]] = {}
        for rows in rows_by_code.values():
            for r in rows:
                dt = r.get("date")
                c = r.get("close")
                if dt and c is not None:
                    by_date.setdefault(dt, []).append(c)
        dates = sorted(by_date)
        closes: List[Optional[float]] = []
        last: Optional[float] = None
        for d in dates:
            cs = by_date[d]
            v = sum(cs) / len(cs) if cs else last
            last = v
            closes.append(v)
        if len(closes) < ma_days:
            return True
        ma = _sma([v if v is not None else 0.0 for v in closes], ma_days)
        return _market_ok(closes, ma, len(closes) - 1, True, mode, up_days,
                          rsi_threshold, chg20_max, chg20_max2, chg60_min)
    except Exception:
        return True


def _kdj(highs, lows, closes) -> tuple:
    n = len(closes)
    k = [50.0] * n; d = [50.0] * n
    for i in range(n):
        lo = max(0, i - 8)
        hh = max(highs[lo:i + 1]); ll = min(lows[lo:i + 1])
        rsv = (closes[i] - ll) / (hh - ll) * 100.0 if hh > ll else 50.0
        k[i] = k[i - 1] * 2 / 3 + rsv / 3 if i else rsv
        d[i] = d[i - 1] * 2 / 3 + k[i] / 3 if i else rsv
    return k, d


def _rolling_max(vals: List[float], win: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(vals)
    for i in range(len(vals)):
        out[i] = max(vals[max(0, i - win + 1):i + 1]) if i >= 0 else None
    return out


def _rolling_min(vals: List[float], win: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(vals)
    for i in range(len(vals)):
        out[i] = min(vals[max(0, i - win + 1):i + 1]) if i >= 0 else None
    return out


def _b(m5, m10, m20, m60) -> bool:
    return all(x is not None for x in (m5, m10, m20, m60)) and m5 > m10 > m20 > m60


# ============ 回测配置 ============
DEFAULT_BT_CONFIG: Dict[str, Any] = {
    "strategy": "factor_default",   # factor_default 或 v9 策略 key
    "start": "",                    # 留空 = 最近 120 交易日 或按 window 自动算
    "end": "",                      # 留空 = 最新交易日
    "window": "",                   # 区间长度：30/60/120/250/500，留空=自定义
    "init_cash": 6000,              # 6000 元小资金场景（回测挖掘）
    "top_n": 10,                    # 6000 元下持仓数最优（实际每只约600元）
    "hold_days": 15,                # 6000 元小资金下低频持有更优（噪声小、摩擦少）
    "fee_rate": 0.0005,             # 单边手续费（含滑点）
    "min_score": 48.0,              # 综合因子策略买入门槛（oversold 深度场景候选实际上限 48；55 不可达导致 0 交易）
    "stop_loss": -12.0,             # 止损 %
    "take_profit": 20.0,            # 止盈 %
    "rebalance_every": 2,           # 每 N 个交易日重评一次（挖掘：2 优于 3/1）
    "universe": "all",              # all=全A(逐日按历史数据重新选股) / hits=上次扫描命中池(仅验证当前选股，有前视偏差)
    "max_codes": 400,               # 最大参与标的数
    "pre_days": 60,                 # 指标预热交易日数
    "hits_codes": [],               # universe=hits 时传入
    "market_filter": True,          # 大盘等权指数过滤：不满足时机窗口时空仓
    "market_filter_mode": "oversold", # above=指数>20日线；strong=指数>20日线且20日线上行；oversold=指数RSI14<阈值（超卖反弹入场，均值回归市显著占优）
    "market_rsi_threshold": 40.0,   # oversold 模式：指数 RSI14 低于该值才允许买入
    "market_chg20_max": -14.0,      # oversold 深度主条件：大盘20日涨幅低于该值(%)才买入，如-14.0；None=关闭（与回测页界面默认一致）
    "market_chg20_max2": -10.0,     # oversold 次条件「牛市回调」：主条件未满足时，20日跌幅达到该值(%)（较浅，与回测页界面默认一致）
    "market_chg60_min": 0.0,        # oversold 次条件：60日趋势下限(%)，60日涨幅高于该值才算上升趋势，如0.0（与回测页界面默认一致）
    "ma_up_days": 3,                # MA20 上行判断回看天数
    "max_buy_pct": 6.0,             # 当日涨幅超过该值(%)不追高；None/<=0 表示不限制（6000元场景挖掘：6 优于 8）
    "max_cash_pct": 1.0,            # 每个调仓日最多部署当前现金的比例（分批建仓，防止候选少时重仓锁死资金）；1.0=全部
    "config": None,                 # 策略配置（strategy_config.json 内容）
}


def _fit_top_n_to_cash(top_n: int, init_cash: float,
                       min_per_stock: float = 600.0) -> int:
    """持仓数随本金自适应：每只持仓至少保留约 min_per_stock 元预算
    （≈1 手低价股），防止小资金 + 大 top_n 导致多数标的一手都买不起
    而实际空仓。返回有效 top_n（1 ~ 传入值，随资金缩水）。"""
    cash = float(init_cash or 0)
    tn = int(top_n or 1)
    if cash <= 0:
        return max(1, tn)
    return max(1, min(tn, max(1, int(cash / min_per_stock))))


# ============ 主回测 ============
def run_backtest(cfg: Optional[Dict[str, Any]] = None,
                 progress_cb: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
    """运行回测。progress_cb(msg, pct)。

    返回 {metrics, equity, trades, coverage, config, elapsed}
    """
    c = dict(DEFAULT_BT_CONFIG)
    c.update(cfg or {})
    t0 = time.time()

    def prog(msg: str, pct: int):
        if progress_cb:
            progress_cb(msg, pct)

    strategy_key = c["strategy"]
    use_factor = (strategy_key == "factor_default")
    # 持仓数随本金自适应：6000 元下实际最多持仓约 10 只
    c["top_n"] = _fit_top_n_to_cash(c.get("top_n"), c.get("init_cash"))
    # 回测只覆盖「本地历史(L) 且可回放」因子；
    # 其余因子（在线/实时/环境）不参与 defs，权重归一化时也不会稀释总分。
    # 筛选过滤链（行情/指标过滤）与扫描端共用同一套代码（screen_common），
    # 默认筛选条件与扫描界面默认一致（主板 + 非ST）；显式传 filters={} 表示关闭。
    if c.get("filters") is None:
        c["filters"] = DEFAULT_SCAN_FILTERS
    # 完整因子定义（score_factor_local 内部会再过滤为本地可回测子集，
    # 保证扫描/回测用同一份 defs 判定）
    defs_full = build_factor_defs(c.get("config"))
    defs = [f for f in defs_full
            if f.get("enabled", True) and f.get("backtestable", True)
            and f.get("source") == SRC_LOCAL]
    rmap = build_rules_map(c.get("config"))

    # ---- 1. 确定标的池 ----
    universe: List[str] = []
    if c.get("universe") == "hits" and c.get("hits_codes"):
        universe = [x for x in c["hits_codes"] if len(x) == 6]
    if not universe:
        universe = _sampled_universe(A_SHARE_PREFIXES, c["max_codes"])
    prog(f"回测标的选择完成：{len(universe)} 只", 3)

    # ---- 2. 加载 K 线 ----
    dates_end = c["end"] or _latest_end()
    if not c.get("start") and c.get("window"):
        c["start"] = calc_window_start(dates_end, c["window"])
    pre_days = c.get("pre_days", DEFAULT_BT_CONFIG["pre_days"])
    if c.get("start"):
        pre_start = _default_start(c["start"], pre_days)
    else:
        pre_start = _default_start(dates_end, 120 + pre_days)
    rows_map = _load_rows(universe, pre_start, dates_end)
    if not rows_map:
        raise RuntimeError("回测区间内无任何K线数据，请检查日期范围或标的池")
    prog(f"K线加载完成：{len(rows_map)} 只", 8)

    # ---- 3. 预计算指标序列 ----
    series_map: Dict[str, IndicatorSeries] = {}
    for code, rows in rows_map.items():
        s = IndicatorSeries(code, rows)
        if s.n >= 60:
            series_map[code] = s
    if not series_map:
        raise RuntimeError("无满足 60 个交易日数据的标的")
    prog(f"指标预计算完成：{len(series_map)} 只", 15)

    # ---- 4. 交易日轴 ----
    axis = _market_axis(series_map, c["start"], dates_end)
    if len(axis) < 10:
        raise RuntimeError("回测区间交易日不足 10 天")

    # ---- 4.5 大盘环境：全池等权指数 + MA20（用于大盘过滤/择时）----
    market_close: List[Optional[float]] = []
    last_mc: Optional[float] = None
    for date in axis:
        cs = []
        for s in series_map.values():
            i = s.index_at(date)
            if i >= 0:
                cs.append(s._data["close"][i])
        v = sum(cs) / len(cs) if cs else last_mc
        last_mc = v
        market_close.append(v)
    market_ma20 = _sma([v if v is not None else 0.0 for v in market_close], 20)
    prog("开始逐日模拟...", 16)

    # ---- 5. 逐日模拟 ----
    cash = float(c["init_cash"])
    holdings: Dict[str, dict] = {}
    nav_curve: List[List] = []
    trades: List[dict] = []
    covered_factor_keys = [f["key"] for f in defs]
    excluded_keys = [f["key"] for f in DEFAULT_FACTOR_DEFS
                     if f["key"] not in covered_factor_keys]

    names = {code: str(rows[-1].get("name", code))
             for code, rows in rows_map.items()}

    for di, date in enumerate(axis):
        # 2a. 卖出：止损/止盈/持有到期
        for code in list(holdings.keys()):
            s = series_map[code]
            ctx = s.ctx_at(date)
            if ctx is None:
                continue
            px = ctx["close"]
            h = holdings[code]
            pnl_pct = (px / h["buy_price"] - 1) * 100.0
            sl = c.get("stop_loss")
            tp = c.get("take_profit")
            reason = None
            if sl is not None and pnl_pct <= sl:
                reason = "止损"
            elif tp is not None and pnl_pct >= tp:
                reason = "止盈"
            elif di - h["buy_di"] >= c["hold_days"]:
                reason = "持有到期"
            if reason:
                sell_val = h["shares"] * px
                fee = sell_val * c["fee_rate"]
                cash += sell_val - fee
                trades.append({
                    "code": code, "name": h["name"],
                    "buy_date": h["buy_date"], "buy_price": round(h["buy_price"], 3),
                    "sell_date": date, "sell_price": round(px, 3),
                    "shares": h["shares"],
                    "pnl": round(sell_val - fee - h["cost"], 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "hold_days": di - h["buy_di"],
                    "reason": reason,
                })
                del holdings[code]

        # 2b. 买入（调仓日）
        # 大盘过滤：全池等权指数跌破20日线 -> 空仓等待，不买入
        skip_buy = not _market_ok(
            market_close, market_ma20, di,
            c.get("market_filter", True),
            c.get("market_filter_mode", "strong"),
            c.get("ma_up_days", 3),
            c.get("market_rsi_threshold", 40.0),
            c.get("market_chg20_max"),
            c.get("market_chg20_max2"),
            c.get("market_chg60_min"))
        if di % c["rebalance_every"] == 0 and not skip_buy:
            cands: List[tuple] = []
            max_buy_pct = c.get("max_buy_pct") or None
            for code, s in series_map.items():
                if code in holdings or not s.has_date(date):
                    continue
                # 两端共用判定（judge_at，与扫描端 process 同源）：
                # 过滤链(行情/指标/在线) + 策略命中 + 参数限制(不追高)。
                # 大盘过滤在外层已判定（skip_buy），此处 market_ok 恒为 True；
                # 回测无历史在线数据：online 默认 {} 按“数据缺失放行”。
                r = judge_at(s, date, c["filters"], True, max_buy_pct,
                             c["min_score"], defs_full, rmap, use_factor,
                             strategy_key)
                if r is not None:
                    cands.append((code, r["scored"]["total"]))
            cands.sort(key=lambda x: -x[1])
            # 单笔仓位上限 = cash/top_n：候选稀少时也避免把全部资金
            # 押进少数几只（锁死现金、错过后续更高置信度的入场窗口）。
            # max_cash_pct 限制每个调仓日的总部署上限（默认 1.0=不限）。
            # 小资金（上限不足约1手）放弃单笔上限，保持集中度与可行性。
            daily_cap = cash * c.get("max_cash_pct", 1.0)
            slots = max(1, min(c["top_n"], len(cands)))
            budget = daily_cap / slots
            per_cap = cash / max(1, c["top_n"]) * c.get("pos_cap_mult", 1.0)
            if per_cap >= 1200.0:
                budget = min(budget, per_cap)
            spent_today = 0.0
            for code, _sc in cands[:c["top_n"]]:
                if cash <= 0 or spent_today >= daily_cap - 1e-9:
                    break
                px = series_map[code].ctx_at(date)["close"]
                if px <= 0:
                    continue
                shares = int(budget / (px * 100)) * 100
                if shares <= 0:
                    continue
                cost = shares * px
                fee = cost * c["fee_rate"]
                if cost + fee > cash or spent_today + cost + fee > daily_cap + 1e-9:
                    continue
                cash -= cost + fee
                spent_today += cost + fee
                holdings[code] = {
                    "code": code, "name": names.get(code, code),
                    "shares": shares, "buy_price": px,
                    "buy_date": date, "buy_di": di, "cost": cost + fee,
                }

        # 2c. 净值
        mv = cash
        for code, h in holdings.items():
            ctx = series_map[code].ctx_at(date)
            if ctx:
                mv += h["shares"] * ctx["close"]
        nav_curve.append([date, round(mv / c["init_cash"], 6)])

        if di % 5 == 0 or di == len(axis) - 1:
            pct = 16 + int((di + 1) / len(axis) * 80)
            prog(f"模拟第 {di + 1}/{len(axis)} 日，持仓 {len(holdings)} 只", min(pct, 96))

    # 收盘：强制平仓
    for code, h in list(holdings.items()):
        ctx = series_map[code].ctx_at(axis[-1])
        px = ctx["close"] if ctx else h["buy_price"]
        sell_val = h["shares"] * px
        fee = sell_val * c["fee_rate"]
        cash += sell_val - fee
        trades.append({
            "code": code, "name": h["name"],
            "buy_date": h["buy_date"], "buy_price": round(h["buy_price"], 3),
            "sell_date": axis[-1], "sell_price": round(px, 3),
            "shares": h["shares"],
            "pnl": round(sell_val - fee - h["cost"], 2),
            "pnl_pct": round((px / h["buy_price"] - 1) * 100, 2),
            "hold_days": len(axis) - 1 - h["buy_di"],
            "reason": "期末平仓",
        })
    holdings.clear()

    metrics = _calc_metrics(nav_curve, trades)
    prog("回测完成", 100)
    return {
        "metrics": metrics,
        "equity": nav_curve,
        "trades": trades,
        "coverage": {
            "factors": covered_factor_keys,
            "excluded": excluded_keys,
            "note": "回测仅覆盖本地历史(L)可回放因子：趋势/均线/量能/动量/波动；"
                    "在线接口(O)/实时盘口(R)及板块题材市场环境因子未参与回测，"
                    "故综合分在回测中按这 5 个因子归一化。"
                    "买入判定（行情/指标过滤链 + 策略命中 + 不追高/大盘限制）"
                    "与扫描端共用同一套代码（screen_common），"
                    "默认筛选条件与扫描一致（主板+非ST）",
        },
        "config": {**c, "config": None},
        "elapsed": round(time.time() - t0, 1),
    }


def _sampled_universe(prefixes: List[str], max_codes: int) -> List[str]:
    """抽样选取参与回测的标的（均匀分布，控制内存与耗时）。

    统一走 load_market_rows（已验证稳定可用的查询路径）。
    max_codes <= 0 表示全量回测（不抽样）。
    """
    try:
        m = load_market_rows(prefixes, _default_start("", 30), _latest_end())
    except Exception:
        return []
    codes = sorted(m.keys())
    if not codes:
        return []
    # max_codes <= 0 表示全量回测（不抽样）
    if not max_codes or max_codes <= 0 or len(codes) <= max_codes:
        return codes
    step = len(codes) / max_codes
    return [codes[int(i * step)] for i in range(max_codes)]


def _load_rows(codes: List[str], start: str, end: str) -> Dict[str, List[dict]]:
    """逐 code 加载区间 K 线（复用 load_market_rows 稳定路径）。"""
    out: Dict[str, List[dict]] = {}
    for code in codes:
        try:
            part = load_market_rows([code], start, end)
            if code in part and part[code]:
                out[code] = part[code]
        except Exception:
            continue
    return out


def _market_axis(series_map: Dict[str, IndicatorSeries], start: str,
                 end: str) -> List[str]:
    """交易日轴：取数据最全股票的日期（过滤出 start/end 区间）。"""
    best = max(series_map.values(), key=lambda s: s.n)
    axis = [d for d in best.dates if (not start or d >= start) and d <= end]
    return axis


def _default_start(end: str, back_days: int) -> str:
    """回推 N 个自然日作为起始日期。"""
    from datetime import datetime, timedelta
    try:
        dt = datetime.strptime(end, "%Y%m%d")
    except Exception:
        dt = datetime.now()
    return (dt - timedelta(days=back_days * 1.6)).strftime("%Y%m%d")


def _latest_end() -> str:
    from strategy_data import END
    return END


def _calc_metrics(nav_curve: List[List], trades: List[dict]) -> Dict[str, Any]:
    n = len(nav_curve)
    if n < 2:
        return {"total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
                "sharpe": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
                "trade_count": len(trades), "days": n}
    navs = [x[1] for x in nav_curve]
    total = (navs[-1] - 1) * 100.0
    annual = ((navs[-1]) ** (250.0 / n) - 1) * 100.0 if navs[-1] > 0 else -100.0
    peak = navs[0]; mdd = 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100.0)
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, n)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    sharpe = (mean / (var ** 0.5) * (250 ** 0.5)) if var > 0 else 0.0
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
    return {
        "total_return": round(total, 2),
        "annual_return": round(annual, 2),
        "max_drawdown": round(mdd, 2),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2) if pf != float("inf") else 999.0,
        "trade_count": len(trades),
        "days": n,
    }
