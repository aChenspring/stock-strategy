"""扫描与回测共用的筛选判定（同一套代码，只是数据时点不同）。

- ``passes_market_filters`` / ``passes_indicator_filters`` / ``passes_online_filters``：
  扫描端（main.py）与回测端（backtest.py）共用同一实现，避免两端筛选口径漂移。
- ``evaluate_buy``：把 过滤链 + 策略命中 + 参数限制(不追高/大盘) 组合成最终买入判定，
  供扫描与回测调用。score/strat_hit 由调用方按各自性能路径计算后传入。
"""
from typing import Any, Dict, List, Optional
from math import isfinite

try:
    from stock_sdk import bk
except Exception:  # pragma: no cover - 接口缺失时行业过滤走异常放行
    bk = None

# factors / strategy_schema 均不反向依赖 screen_common，顶层导入安全。
# 与 factors 共享 build_factor_ctx，保证两端 ctx 摊平逻辑完全一致。
from factors import build_factor_ctx  # noqa: E402
from strategy_schema import (  # noqa: E402
    SRC_LOCAL, build_rules_map, score_factor_set, total_score,
)


def _safe_float(v) -> Optional[float]:
    try:
        x = float(v)
        return x if isfinite(x) else None
    except (TypeError, ValueError):
        return None


def score_factor_local(factor_defs: List[dict], valid: List[dict], ind: Dict[str, Any],
                       rules_map: Optional[Dict[str, List[dict]]] = None) -> Dict[str, Any]:
    """两端共用的「本地可回测」综合评分（结构与 factors.score_stock 相同）。

    板块/市场/在线字段统一置 0（回测没有历史环境/在线数据），并只保留
    本地(L) 且可回放 的因子参与权重归一化。这样扫描端『今天』与回测端
    『任意调仓日』用同一份代码算出同一个综合分，命中集合才严格可比。

    返回 {factor_scores, total, details}，可直接替代 score_stock 用于判定与展示。
    """
    ctx = build_factor_ctx(valid, ind, 0.0, 0.0, {})
    defs = [f for f in factor_defs
            if f.get("enabled", True) and f.get("backtestable", True)
            and f.get("source") == SRC_LOCAL]
    rmap = rules_map if rules_map is not None else build_rules_map(None)
    scores = score_factor_set(defs, ctx, rmap, active_sources={SRC_LOCAL})
    total = total_score(defs, scores)
    return {
        "factor_scores": scores,
        "total": total,
        "details": {
            "close": ctx["close"], "pct_chg": ctx["pct"],
            "amount": ctx["amount"], "turnover": ctx["turnover"],
            "vol_ratio": ctx["vol_ratio"], "profit_ratio": ctx["profit_ratio"],
            "limit_up_5": ctx["limit_up_5"], "is_break": ctx["is_break"],
            "bull_arrange": ctx["bull_arrange"],
            "ma5": ctx["ma5"], "ma10": ctx["ma10"],
            "ma20": ctx["ma20"], "ma60": ctx["ma60"],
            "macd": ctx["macd"], "rsi6": ctx["rsi6"],
            "k": ctx["k"], "d": ctx["d"],
            "main_net": ctx["main_net"], "dde_net": ctx["dde_net"],
            "pe": ctx["pe"], "pb": ctx["pb"],
            "rev_yoy": ctx["rev_yoy"], "profit_yoy": ctx["profit_yoy"],
        },
    }


#: 默认筛选条件 = 全市场（主板/创业板/科创板/北交所）+ 非ST。
#: 回测多轮调优（DEFAULT_BT_CONFIG）是在全市场口径下完成的，扫描端默认必须
#: 对齐该口径，否则两端结果不可比（此前仅主板导致回测收益被严重低估）。
DEFAULT_SCAN_FILTERS: Dict[str, Any] = {
    "boards": {"main": True, "gem": True, "star": True, "bse": True},
    "non_st": True,
}


def passes_market_filters(code: str, valid: List[dict], filters: Dict[str, Any]) -> bool:
    """仅依赖行情行的快速过滤（板块/ST/股价/成交额/换手/涨幅）。

    filters 缺省项视为不限制；filters={} 时全部放行。
    """
    f = filters or {}
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


def passes_indicator_filters(code: str, ind: Dict[str, Any],
                             valid: List[dict], filters: Dict[str, Any]) -> bool:
    """依赖技术指标的技术面过滤（均线/MACD/新高/涨停/RSI/量比）。"""
    f = filters or {}
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


def passes_online_filters(code: str, valid: List[dict],
                          online: Dict[str, Any], ind: Dict[str, Any],
                          filters: Dict[str, Any]) -> bool:
    """依赖在线财务/估值/资金流/行业的过滤。

    数据缺失时按“不限制”放行（与扫描端在线数据不可用时一致）；
    回测端无历史在线数据，传入 online={} 即等效放行。
    """
    f = filters or {}
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
        main_net = (_safe_float(flow.get("main_net_inflow_latest"))
                    or _safe_float(flow.get("main_net_inflow")))
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

    # 概念过滤
    concept = f.get("concept")
    if concept and concept != "全部":
        try:
            boards = bk.get(code, 0, "name")
            if not isinstance(boards, list) or concept not in boards:
                return False
        except Exception:
            return False

    return True


def evaluate_buy(code: str, valid: List[dict], ind: Dict[str, Any],
                 online: Dict[str, Any], filters: Dict[str, Any],
                 market_ok: bool, max_buy_pct: Optional[float],
                 strat_hit: bool, score: float = 0.0,
                 warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """扫描与回测共用的买入判定：过滤链 + 策略命中 + 参数限制。

    - 过滤链（行情/指标/在线）：与扫描端完全同一实现
    - 参数限制：不追高（当日涨幅超 max_buy_pct 不买）+ 大盘过滤（market_ok=False 不买）
    - ``score`` / ``strat_hit`` 由调用方按各自性能路径计算传入（扫描 score_stock、
      回测 score_factor_set O(1) 上下文），此处只做判定组合，保证两端逻辑一致。
    """
    warnings = list(warnings or [])
    market_ok_f = passes_market_filters(code, valid, filters)
    ind_ok = passes_indicator_filters(code, ind, valid, filters)
    online_ok = passes_online_filters(code, valid, online, ind, filters)

    max_buy = max_buy_pct or None
    pct_now = _safe_float(valid[-1].get("pct_chg"))
    no_chase_ok = not (max_buy and max_buy > 0
                       and pct_now is not None and pct_now > max_buy)
    if not no_chase_ok:
        warnings.append(f"不追高：当日涨幅 {pct_now}% 超阈值 {max_buy}%")
    if not market_ok:
        warnings.append("大盘过滤：市场弱势（指数低于MA20或MA20走平）")

    limit_ok = no_chase_ok and bool(market_ok)
    ok = market_ok_f and ind_ok and online_ok and bool(strat_hit) and limit_ok
    return {
        "market_ok_f": market_ok_f,
        "ind_ok": ind_ok,
        "online_ok": online_ok,
        "strat_hit": bool(strat_hit),
        "no_chase_ok": no_chase_ok,
        "limit_ok": limit_ok,
        "ok": ok,
        "score": score,
        "warnings": warnings,
    }
