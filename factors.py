# -*- coding: utf-8 -*-
"""
14 因子评分引擎：每因子 0-10 分，加权合成 100 分制综合分。

从 v1 硬编码版升级为「配置驱动」版：
- 因子定义/子因子规则/阈值/权重全部声明在 strategy_schema.py
- score_stock 读取用户配置（strategy_config.json），界面可迭代调整
- 默认配置与原硬编码逻辑逐规则等价，行为 100% 一致
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Dict, List, Optional

from strategy_data import (
    _finite,
    valid_trading_rows,
    compute_board_env,
    compute_market_env,
)
from strategy_schema import (
    SRC_LOCAL,
    SRC_ONLINE,
    SRC_REALTIME,
    ONLINE_TTL_HOURS,
    build_factor_defs,
    build_rules_map,
    score_factor_set,
    total_score,
)


# ============ 因子定义（兼容旧引用，唯一事实源在 strategy_schema） ============
FACTORS = [
    {"key": "trend",     "name": "趋势结构", "weight": 0.05},
    {"key": "ma_system", "name": "均线系统", "weight": 0.05},
    {"key": "volume",    "name": "量能活跃", "weight": 0.05},
    {"key": "main_flow", "name": "主力行为", "weight": 0.05},
    {"key": "dde",       "name": "DDE大单",  "weight": 0.05},
    {"key": "momentum",  "name": "动量指标", "weight": 0.05},
    {"key": "volatility","name": "波动风险", "weight": 0.05},
    {"key": "board",     "name": "板块环境", "weight": 0.05},
    {"key": "growth",    "name": "基本面增长", "weight": 0.05},
    {"key": "valuation", "name": "估值水平", "weight": 0.05},
    {"key": "theme",     "name": "题材催化", "weight": 0.05},
    {"key": "order_book","name": "盘口承接", "weight": 0.05},
    {"key": "position",  "name": "执行位置", "weight": 0.05},
    {"key": "market",    "name": "市场环境", "weight": 0.05},
]


# ============ 因子数据来源分层 ============
#   L 本地历史数据（日K/指标/板块）  -> end 不变即稳定，快照可长期复用
#   O 在线接口数据（财务/估值/资金流） -> 接口数据会更新，需按 TTL 替换缓存
#   R 盘中实时（盘口承接/执行位置）   -> 当前用日K涨跌幅代理；接入真盘口后盘中必须重算
FACTOR_SOURCES: Dict[str, str] = {
    "trend": SRC_LOCAL,
    "ma_system": SRC_LOCAL,
    "volume": SRC_LOCAL,
    "main_flow": SRC_ONLINE,
    "dde": SRC_ONLINE,
    "momentum": SRC_LOCAL,
    "volatility": SRC_LOCAL,
    "board": SRC_LOCAL,
    "growth": SRC_ONLINE,
    "valuation": SRC_ONLINE,
    "theme": SRC_LOCAL,
    "order_book": SRC_REALTIME,
    "position": SRC_REALTIME,
    "market": SRC_LOCAL,
}


def _clamp01(value: float) -> float:
    """限制到 0-1"""
    return max(0.0, min(1.0, value))


def _score_to_10(value: float) -> float:
    """0-1 归一化值转 0-10 分"""
    return _clamp01(value) * 10.0


# ============ 基础字段上下文构造（规则引擎输入） ============
def build_factor_ctx(valid, ind, board_score, market_score, online) -> Dict[str, Any]:
    """把单只股票的快照数据摊平成规则引擎可寻址的字段字典。

    字段名与 strategy_schema.BASIC_FIELDS 一一对应。
    """
    last = valid[-1]
    close = _finite(last.get("close")) or 0
    pct = _finite(last.get("pct_chg")) or 0
    amount = _finite(last.get("amount")) or 0
    turnover = _finite(last.get("turnover")) or 0
    volume = _finite(last.get("volume")) or 0
    high = _finite(last.get("high")) or close
    low = _finite(last.get("low")) or close
    open_ = _finite(last.get("open")) or close
    amplitude = _finite(last.get("amplitude")) or 0

    closes = [_finite(r.get("close")) or 0 for r in valid]
    highs = [_finite(r.get("high")) or 0 for r in valid]
    lows = [_finite(r.get("low")) or 0 for r in valid]
    vols = [_finite(r.get("volume")) or 0 for r in valid]

    high_20 = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    low_60 = min(lows[-60:]) if len(lows) >= 60 else min(lows)
    high_60 = max(highs[-60:]) if len(highs) >= 60 else max(highs)

    vol_ratio = 1.0
    if len(vols) >= 6 and sum(vols[-6:-1]) > 0:
        avg5 = sum(vols[-6:-1]) / 5
        vol_ratio = volume / avg5 if avg5 > 0 else 1.0

    # 近5/20日涨跌幅（超跌反弹策略核心：低位企稳、不追高）
    chg5 = (close / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None
    chg20 = (close / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else None

    limit_up_5 = 0
    for i in range(max(0, len(valid) - 5), len(valid)):
        p = _finite(valid[i].get("pct_chg"))
        if p is not None and p >= 9.5:
            limit_up_5 += 1

    is_break = close >= high_20 * 0.995

    profit_ratio = 0.5
    if high_60 > low_60:
        profit_ratio = (close - low_60) / (high_60 - low_60)

    ma5 = ind.get("ma5")
    ma10 = ind.get("ma10")
    ma20 = ind.get("ma20")
    ma60 = ind.get("ma60")
    bull_arrange = all(x is not None for x in (ma5, ma10, ma20, ma60)) and \
        ma5 > ma10 > ma20 > ma60

    flow = online.get("flow") or {}
    fund = online.get("fund") or {}
    val = online.get("val") or {}
    main_net = _finite(flow.get("main_net_inflow")) or 0
    dde_net = _finite(flow.get("dde_net")) or 0
    rev_yoy = _finite(fund.get("revenue_yoy")) or 0
    profit_yoy = _finite(fund.get("profit_yoy")) or 0
    pe = _finite(val.get("pe_ratio")) or _finite(fund.get("pe_ratio"))
    pb = _finite(val.get("pb_ratio")) or _finite(fund.get("pb_ratio"))

    rsi6 = ind.get("rsi6")
    k = ind.get("k")
    d = ind.get("d")
    kd_strong = bool(k is not None and d is not None and k > d and k > 50)
    kd_weak = bool(k is not None and d is not None and k < d)

    return {
        "close": close, "pct": pct, "amount": amount, "turnover": turnover,
        "volume": volume, "amplitude": amplitude,
        "chg5": chg5, "chg20": chg20,
        "vol_ratio": vol_ratio, "limit_up_5": limit_up_5,
        "is_break": is_break, "profit_ratio": profit_ratio,
        "bull_arrange": bull_arrange,
        "dev_ma20": (close / ma20 - 1) if ma20 else None,
        "dev_ma60": (close / ma60 - 1) if ma60 else None,
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "macd": ind.get("macd"),
        "rsi6": rsi6, "k": k, "d": d,
        "kd_strong": kd_strong, "kd_weak": kd_weak,
        "board_score": board_score, "market_score": market_score,
        "main_net": main_net, "dde_net": dde_net,
        "rev_yoy": rev_yoy, "profit_yoy": profit_yoy,
        "pe": pe, "pb": pb,
        # 实时盘口代理：当前用当日涨跌幅
        "order_book_pct": pct, "position_pct": pct,
    }


# ============ 单个股票因子计算 ============
def score_stock(
    code: str,
    rows: List[dict],
    ind: Dict[str, Any],
    board_score: float,
    market_score: float,
    online: Dict[str, Any],
    config: Optional[dict] = None,
    factor_defs: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """
    计算单只股票的 14 因子分。
    online: 在线数据 {fund: {...}, val: {...}, flow: {...}}
    config: 用户策略配置（strategy_schema.load_strategy_config()），None=默认
    factor_defs: 预构建的因子定义（回测等批量场景复用，避免反复构建）

    返回 {factor_scores: {...}, total: float, details: {...}}
    """
    valid = valid_trading_rows(rows)
    if not valid:
        return {"factor_scores": {}, "total": 0.0, "details": {}}

    ctx = build_factor_ctx(valid, ind, board_score, market_score, online)
    defs = factor_defs if factor_defs is not None else build_factor_defs(config)
    rmap = build_rules_map(config)

    # 在线数据整体不可用（fund/val/flow 全空）时，在线/实时因子给中性分，
    # 避免 0 分稀释综合分；本地因子照常参与排序，结果不受影响。
    online_empty = not any(online.get(k) for k in ("fund", "val", "flow"))
    scores = score_factor_set(defs, ctx, rmap, online_empty=online_empty)
    total = total_score(defs, scores)

    return {
        "factor_scores": scores,
        "total": total,
        "details": {
            "close": ctx["close"],
            "pct_chg": ctx["pct"],
            "amount": ctx["amount"],
            "turnover": ctx["turnover"],
            "vol_ratio": ctx["vol_ratio"],
            "profit_ratio": ctx["profit_ratio"],
            "limit_up_5": ctx["limit_up_5"],
            "is_break": ctx["is_break"],
            "bull_arrange": ctx["bull_arrange"],
            "ma5": ctx["ma5"], "ma10": ctx["ma10"],
            "ma20": ctx["ma20"], "ma60": ctx["ma60"],
            "macd": ctx["macd"],
            "rsi6": ctx["rsi6"], "k": ctx["k"], "d": ctx["d"],
            "main_net": ctx["main_net"],
            "dde_net": ctx["dde_net"],
            "pe": ctx["pe"], "pb": ctx["pb"],
            "rev_yoy": ctx["rev_yoy"], "profit_yoy": ctx["profit_yoy"],
        },
    }
