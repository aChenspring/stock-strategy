
# -*- coding: utf-8 -*-
"""
v9 策略框架：9 个策略的硬条件定义。
硬条件映射到可获取的数据：行情技术面（rd）+ 在线财务/估值。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from strategy_data import _finite, valid_trading_rows


# ============ 工具 ============
def _get(row: Optional[dict], field: str) -> Optional[float]:
    if not row:
        return None
    return _finite(row.get(field))


def _calc_indicators_from_rows(valid: List[dict],
                               external: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """从有效K线行计算简单技术指标（不依赖zb，供策略硬条件使用）。
    external 可传入 compute_indicators 产出的指标（含 ma*/macd/rsi6），
    命中时跳过最耗时的 ema/MACD/RSI 重算，仅补算轻量的高低点/量能键（扫描提速）。"""
    ext = external or {}
    if ext.get("ma5") is not None and all(k in ext for k in
            ("ma10", "ma20", "ma60", "macd", "rsi6")):
        closes = [_get(r, "close") or 0 for r in valid]
        highs = [_get(r, "high") or 0 for r in valid]
        lows = [_get(r, "low") or 0 for r in valid]
        vols = [_get(r, "volume") or 0 for r in valid]
        n = len(closes)
        return {
            "close": closes[-1] if closes else None,
            "ma5": ext["ma5"],
            "ma10": ext["ma10"],
            "ma20": ext["ma20"],
            "ma60": ext["ma60"],
            "high20": max(highs[-20:]) if n >= 20 else (max(highs) if highs else None),
            "high60": max(highs[-60:]) if n >= 60 else (max(highs) if highs else None),
            "low60": min(lows[-60:]) if n >= 60 else (min(lows) if lows else None),
            "vol_avg5": (sum(vols[-5:]) / 5) if n >= 5 else None,
            "vol": vols[-1] if vols else None,
            "macd": ext["macd"],
            "rsi6": ext["rsi6"],
        }
    closes = [_get(r, "close") or 0 for r in valid]
    highs = [_get(r, "high") or 0 for r in valid]
    lows = [_get(r, "low") or 0 for r in valid]
    vols = [_get(r, "volume") or 0 for r in valid]
    n = len(closes)
    if n == 0:
        return {}

    def ma(p: int) -> Optional[float]:
        if n < p:
            return None
        return sum(closes[-p:]) / p

    def ema(values: List[float], p: int) -> Optional[float]:
        if len(values) < p:
            return None
        k = 2.0 / (p + 1)
        result = values[0]
        for v in values[1:]:
            result = v * k + result * (1 - k)
        return result

    def macd_value(values: List[float]) -> Optional[float]:
        ema12 = ema(values, 12)
        ema26 = ema(values, 26)
        if ema12 is None or ema26 is None:
            return None
        dif = ema12 - ema26
        # dea 取最后 9 根 DIF 的 EMA
        dif_series = []
        for i in range(len(values)):
            if i + 1 < 26:
                continue
            e12 = ema(values[: i + 1], 12)
            e26 = ema(values[: i + 1], 26)
            if e12 is not None and e26 is not None:
                dif_series.append(e12 - e26)
        dea = ema(dif_series, 9) if len(dif_series) >= 9 else None
        if dea is None:
            return None
        return (dif - dea) * 2

    def rsi_value(values: List[float], p: int = 6) -> Optional[float]:
        if len(values) < p + 1:
            return None
        gains = []
        losses = []
        for i in range(1, p + 1):
            change = values[-i] - values[-i - 1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        avg_gain = sum(gains) / p
        avg_loss = sum(losses) / p
        if avg_loss == 0:
            return 100.0
        return 100.0 - 100.0 / (1 + avg_gain / avg_loss)

    return {
        "close": closes[-1] if closes else None,
        "ma5": ma(5),
        "ma10": ma(10),
        "ma20": ma(20),
        "ma60": ma(60),
        "high20": max(highs[-20:]) if n >= 20 else (max(highs) if highs else None),
        "high60": max(highs[-60:]) if n >= 60 else (max(highs) if highs else None),
        "low60": min(lows[-60:]) if n >= 60 else (min(lows) if lows else None),
        "vol_avg5": (sum(vols[-5:]) / 5) if n >= 5 else None,
        "vol": vols[-1] if vols else None,
        "macd": macd_value(closes),
        "rsi6": rsi_value(closes, 6),
    }


# ============ 策略硬条件 ============
def _check_core_common(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9Core 传统成长 + v9Common 公共条件"""
    fund = online.get("fund") or {}
    val = online.get("val") or {}

    pe = _finite(val.get("pe_ratio")) or _finite(fund.get("pe_ratio"))
    pb = _finite(val.get("pb_ratio")) or _finite(fund.get("pb_ratio"))
    roe = _finite(fund.get("roe"))
    debt = _finite(fund.get("debt_to_assets"))
    cash = _finite(fund.get("operating_cash_flow"))
    profit_yoy = _finite(fund.get("profit_yoy"))
    rev_yoy = _finite(fund.get("revenue_yoy"))

    # 公共：上市>500天（用K线数近似）
    if len(valid) < 60:
        return False

    # PE<60 或 PB<5
    if pe is not None and pe > 0 and pe >= 60:
        if pb is None or pb >= 5:
            return False
    # ROE>8%
    if roe is not None and roe <= 8:
        return False
    # 负债<70%
    if debt is not None and debt >= 70:
        return False
    # 经营现金流>0
    if cash is not None and cash <= 0:
        return False
    # 净利增速>20% 或 营收增速>15%
    if profit_yoy is not None and rev_yoy is not None:
        if not (profit_yoy > 20 or rev_yoy > 15):
            return False
    return True


def _check_tech(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9Tech 硬科技替代估值"""
    fund = online.get("fund") or {}
    val = online.get("val") or {}

    pe = _finite(val.get("pe_ratio")) or _finite(fund.get("pe_ratio"))
    pb = _finite(val.get("pb_ratio")) or _finite(fund.get("pb_ratio"))
    ps = _finite(val.get("ps_ratio")) or _finite(fund.get("ps_ratio"))
    debt = _finite(fund.get("debt_to_assets"))
    rev_yoy = _finite(fund.get("revenue_yoy"))
    profit_yoy = _finite(fund.get("profit_yoy"))

    if len(valid) < 60:
        return False

    # 硬科技不强制PE<100；满足 PS≤35 或 PB≤12 或 PE≤180
    val_ok = False
    if ps is not None and ps <= 35:
        val_ok = True
    elif pb is not None and pb <= 12:
        val_ok = True
    elif pe is not None and pe <= 180:
        val_ok = True
    if not val_ok:
        return False

    # 营收增速>15% 或 扣非增速>20%
    if rev_yoy is not None and profit_yoy is not None:
        if not (rev_yoy > 15 or profit_yoy > 20):
            return False
    # 负债<70%
    if debt is not None and debt >= 70:
        return False
    return True


def _check_a1(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9A1 核心质量趋势回踩"""
    close = calc.get("close")
    ma20 = calc.get("ma20")
    ma60 = calc.get("ma60")
    if close is None or ma20 is None or ma60 is None:
        return False
    # MA20>MA60 且 收盘>MA60
    if not (ma20 > ma60 and close > ma60):
        return False
    # 收盘价在MA20上方 -2%~+12%
    dev = close / ma20 - 1
    if not (-0.02 <= dev <= 0.12):
        return False
    # 量比>1.2
    vol = calc.get("vol")
    vol_avg5 = calc.get("vol_avg5")
    if vol and vol_avg5 and vol_avg5 > 0:
        if vol / vol_avg5 <= 1.2:
            return False
    # 获利盘<85%（代理：价格分位）
    high60 = calc.get("high60")
    low60 = calc.get("low60")
    if high60 and low60 and high60 > low60:
        profit = (close - low60) / (high60 - low60)
        if profit >= 0.85:
            return False
    return True


def _check_a2(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9A2 行业龙头业绩趋势"""
    fund = online.get("fund") or {}
    val = online.get("val") or {}
    close = calc.get("close")
    ma20 = calc.get("ma20")
    ma60 = calc.get("ma60")
    roe = _finite(fund.get("roe"))
    profit_yoy = _finite(fund.get("profit_yoy"))
    market_cap = _finite(val.get("market_cap"))

    # 市值>300亿
    if market_cap is not None and market_cap < 3e10:
        return False
    # ROE>8%
    if roe is not None and roe <= 8:
        return False
    # 净利增速>15%
    if profit_yoy is not None and profit_yoy <= 15:
        return False
    # 趋势多头
    if close is None or ma20 is None or ma60 is None:
        return False
    if not (close > ma20 > ma60):
        return False
    return True


def _check_a3(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9A3 防守底仓趋势"""
    fund = online.get("fund") or {}
    val = online.get("val") or {}
    close = calc.get("close")
    ma20 = calc.get("ma20")
    ma60 = calc.get("ma60")
    pe = _finite(val.get("pe_ratio")) or _finite(fund.get("pe_ratio"))
    debt = _finite(fund.get("debt_to_assets"))
    cash = _finite(fund.get("operating_cash_flow"))
    roe = _finite(fund.get("roe"))
    div = _finite(fund.get("dividend_yield"))

    if close is None or ma20 is None or ma60 is None:
        return False
    # MA20>MA60 且 收盘>MA60
    if not (ma20 > ma60 and close > ma60):
        return False
    # 负债<50%
    if debt is not None and debt >= 50:
        return False
    # 经营现金流>0
    if cash is not None and cash <= 0:
        return False
    # ROE>8%
    if roe is not None and roe <= 8:
        return False
    # PE<40
    if pe is not None and pe > 0 and pe >= 40:
        return False
    # 股息率>2%
    if div is not None and div <= 2:
        return False
    return True


def _check_screen(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9Screen 综合趋势资金：非ST/营收同比>0/净利同比>0/主力净流入>0/趋势多头排列/MACD>0"""
    # 非 ST
    name = str(valid[-1].get("name", "")) if valid else ""
    if "ST" in name.upper():
        return False

    close = calc.get("close")
    ma20 = calc.get("ma20")
    ma60 = calc.get("ma60")
    macd = calc.get("macd")
    if close is None or ma20 is None or ma60 is None:
        return False
    # 收盘价>MA20 且 MA20>MA60 且 收盘价>MA60
    if not (close > ma20 and ma20 > ma60 and close > ma60):
        return False
    # MACD>0
    if macd is None or macd <= 0:
        return False

    fund = online.get("fund") or {}
    flow = online.get("flow") or {}
    rev_yoy = _finite(fund.get("revenue_yoy"))
    profit_yoy = _finite(fund.get("profit_yoy"))
    main_net = _finite(flow.get("main_net_inflow_latest")) or _finite(flow.get("main_net_inflow"))

    # 营业收入同比>0
    if rev_yoy is not None and rev_yoy <= 0:
        return False
    # 归母净利润同比>0
    if profit_yoy is not None and profit_yoy <= 0:
        return False
    # 主力资金流向>0（最新交易日口径）
    if main_net is not None and main_net <= 0:
        return False
    return True


def _check_b1(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9B1 放量平台突破"""
    close = calc.get("close")
    high20 = calc.get("high20")
    vol = calc.get("vol")
    vol_avg5 = calc.get("vol_avg5")
    if close is None or high20 is None:
        return False
    # 突破20日高点
    if close < high20 * 0.995:
        return False
    # 量比>2
    if vol and vol_avg5 and vol_avg5 > 0:
        if vol / vol_avg5 <= 2:
            return False
    # 换手3%-25%（用最近一根）
    turnover = _finite(valid[-1].get("turnover")) if valid else None
    if turnover is not None and not (3 <= turnover <= 25):
        return False
    # 成交额>5亿
    amount = _finite(valid[-1].get("amount")) if valid else None
    if amount is not None and amount <= 5e8:
        return False
    # 涨幅>3%
    pct = _finite(valid[-1].get("pct_chg")) if valid else None
    if pct is not None and pct <= 3:
        return False
    return True


def _check_b2(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9B2 情绪接力"""
    # 近20日有涨停
    limit_up = False
    for r in valid[-20:]:
        if (_finite(r.get("pct_chg")) or 0) >= 9.5:
            limit_up = True
            break
    if not limit_up:
        return False
    # 当日涨幅>7%
    pct = _finite(valid[-1].get("pct_chg")) if valid else None
    if pct is not None and pct <= 7:
        return False
    # 量比>1.5
    vol = calc.get("vol")
    vol_avg5 = calc.get("vol_avg5")
    if vol and vol_avg5 and vol_avg5 > 0:
        if vol / vol_avg5 <= 1.5:
            return False
    # 换手>3%
    turnover = _finite(valid[-1].get("turnover")) if valid else None
    if turnover is not None and turnover <= 3:
        return False
    return True


def _check_s(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """v9S 小市值弹性"""
    fund = online.get("fund") or {}
    val = online.get("val") or {}
    close = calc.get("close")
    high20 = calc.get("high20")
    market_cap = _finite(val.get("market_cap"))
    profit_yoy = _finite(fund.get("profit_yoy"))
    rev_yoy = _finite(fund.get("revenue_yoy"))

    # 市值<200亿
    if market_cap is not None and market_cap >= 2e10:
        return False
    # 净利增速>30% 且 营收增速>20%
    if profit_yoy is not None and rev_yoy is not None:
        if not (profit_yoy > 30 and rev_yoy > 20):
            return False
    # 突破20日高点
    if close is None or high20 is None:
        return False
    if close < high20 * 0.995:
        return False
    return True


def _check_risk(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> Dict[str, str]:
    """v9Risk 风控：返回风控提示列表"""
    warnings = []
    close = calc.get("close")
    ma20 = calc.get("ma20")
    ma60 = calc.get("ma60")
    fund = online.get("fund") or {}

    # 获利盘>95%
    high60 = calc.get("high60")
    low60 = calc.get("low60")
    if close and high60 and low60 and high60 > low60:
        profit = (close - low60) / (high60 - low60)
        if profit > 0.95:
            warnings.append("获利盘>95%，情绪过热")
    # 单日大涨>9.8%
    pct = _finite(valid[-1].get("pct_chg")) if valid else None
    if pct is not None and pct > 9.8:
        warnings.append("单日涨幅>9.8%，追高风险")
    # 负债>80%
    debt = _finite(fund.get("debt_to_assets"))
    if debt is not None and debt > 80:
        warnings.append("负债率>80%，财务风险")
    # 经营现金流为负
    cash = _finite(fund.get("operating_cash_flow"))
    if cash is not None and cash < 0:
        warnings.append("经营现金流为负")
    # 跌破MA20放量
    vol = calc.get("vol")
    vol_avg5 = calc.get("vol_avg5")
    if close is not None and ma20 is not None and close < ma20:
        if vol and vol_avg5 and vol_avg5 > 0 and vol / vol_avg5 > 1.5:
            warnings.append("跌破MA20且放量，建议减仓")
    # 跌破MA60
    if close is not None and ma60 is not None and close < ma60:
        warnings.append("跌破MA60，建议退出趋势仓")
    return warnings


def _check_low(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """低位修复型：刚站上中期均线且 RSI 未极端，估值合理，主力净流入"""
    close = calc.get("close")
    ma20 = calc.get("ma20")
    ma60 = calc.get("ma60")
    high60 = calc.get("high60")
    rsi6 = calc.get("rsi6")
    if close is None or ma20 is None or ma60 is None:
        return False
    if not (close > ma20 and close > ma60):
        return False
    if high60 is not None and high60 > 0 and close > high60 * 0.85:
        return False
    if rsi6 is not None and (rsi6 < 30 or rsi6 > 70):
        return False
    fund = online.get("fund") or {}
    flow = online.get("flow") or {}
    val = online.get("val") or {}
    pe = _finite(val.get("pe_ratio")) or _finite(fund.get("pe_ratio"))
    pb = _finite(val.get("pb_ratio")) or _finite(fund.get("pb_ratio"))
    main_net = _finite(flow.get("main_net_inflow_latest")) or _finite(flow.get("main_net_inflow"))
    if main_net is not None and main_net <= 0:
        return False
    if pe is not None and pe > 0 and pe >= 60:
        return False
    if pb is not None and pb > 0 and pb >= 6:
        return False
    return True


def _check_stable(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """稳健型：大市值/高 ROE/估值不过高/经营现金流为正/股息"""
    close = calc.get("close")
    ma60 = calc.get("ma60")
    if close is None or ma60 is None:
        return False
    if close < ma60:
        return False
    fund = online.get("fund") or {}
    val = online.get("val") or {}
    market_cap = _finite(val.get("market_cap"))
    pe = _finite(val.get("pe_ratio")) or _finite(fund.get("pe_ratio"))
    pb = _finite(val.get("pb_ratio")) or _finite(fund.get("pb_ratio"))
    roe = _finite(fund.get("roe"))
    debt = _finite(fund.get("debt_to_assets"))
    cash = _finite(fund.get("operating_cash_flow"))
    div = _finite(fund.get("dividend_yield"))
    if market_cap is not None and market_cap < 5e10:
        return False
    if roe is not None and roe <= 10:
        return False
    if debt is not None and debt >= 50:
        return False
    if cash is not None and cash <= 0:
        return False
    if pe is not None and pe > 0 and pe >= 30:
        return False
    if pb is not None and pb > 0 and pb >= 3:
        return False
    if div is not None and div <= 1.5:
        return False
    return True


def _check_trend(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """趋势跟随型：多头排列/MACD>0/主力净流入/业绩正增长/涨幅适中"""
    close = calc.get("close")
    ma20 = calc.get("ma20")
    ma60 = calc.get("ma60")
    macd = calc.get("macd")
    if close is None or ma20 is None or ma60 is None:
        return False
    if not (close > ma20 > ma60):
        return False
    if macd is None or macd <= 0:
        return False
    fund = online.get("fund") or {}
    flow = online.get("flow") or {}
    rev_yoy = _finite(fund.get("revenue_yoy"))
    profit_yoy = _finite(fund.get("profit_yoy"))
    main_net = _finite(flow.get("main_net_inflow_latest")) or _finite(flow.get("main_net_inflow"))
    if rev_yoy is not None and rev_yoy <= 0:
        return False
    if profit_yoy is not None and profit_yoy <= 0:
        return False
    if main_net is not None and main_net <= 0:
        return False
    if len(valid) >= 20:
        prev_close = _finite(valid[-20].get("close"))
        if prev_close and prev_close > 0:
            ret20 = (close - prev_close) / prev_close * 100
            if ret20 < 5 or ret20 > 30:
                return False
    return True


def _check_attack(calc: Dict[str, Any], valid: List[dict], online: Dict[str, Any]) -> bool:
    """进攻型：成交活跃与动量，小市值，放量，近 5 日有涨停，主力净流入"""
    close = calc.get("close")
    ma20 = calc.get("ma20")
    if close is None or ma20 is None:
        return False
    if close < ma20:
        return False
    has_limit = any(
        (_finite(r.get("pct_chg")) or 0) >= 9.5 for r in valid[-5:]
    )
    if not has_limit:
        return False
    vol = calc.get("vol")
    vol_avg5 = calc.get("vol_avg5")
    if vol and vol_avg5 and vol_avg5 > 0:
        if vol / vol_avg5 <= 1.5:
            return False
    turnover = _finite(valid[-1].get("turnover")) if valid else None
    if turnover is not None and turnover <= 3:
        return False
    fund = online.get("fund") or {}
    flow = online.get("flow") or {}
    val = online.get("val") or {}
    market_cap = _finite(val.get("market_cap"))
    profit_yoy = _finite(fund.get("profit_yoy"))
    main_net = _finite(flow.get("main_net_inflow_latest")) or _finite(flow.get("main_net_inflow"))
    if main_net is not None and main_net <= 0:
        return False
    if market_cap is not None and market_cap >= 3e10:
        return False
    if profit_yoy is not None and profit_yoy <= 0:
        return False
    return True


# ============ 策略注册表 ============
# 综合因子策略：无硬条件，命中由「综合因子分 >= min_score」判定（扫描端应用）。
# min_score=55 为参数挖掘得到的最优门槛，与回测 DEFAULT_BT_CONFIG["min_score"] 保持一致。
FACTOR_DEFAULT_MIN_SCORE = 55.0


def _check_factor_default(calc: dict, valid: List[dict], online: Dict[str, Any]) -> bool:
    """综合因子策略无硬条件筛选：命中由综合分门槛决定，此处恒为 True。"""
    return True


def get_strategies() -> List[Dict[str, Any]]:
    """返回所有扫描策略定义：factor_default 综合因子策略 + v9 硬条件策略。

    含 ``min_score`` 的策略（综合因子）由调用方按综合分门槛判定命中，
    其余策略按 ``check`` 硬条件判定。"""
    return [
        {
            "key": "factor_default",
            "name": "综合因子策略",
            "desc": "14因子加权综合分≥55（回测挖掘最优门槛，可在策略页迭代编辑因子与权重）",
            "check": _check_factor_default,
            "min_score": FACTOR_DEFAULT_MIN_SCORE,
        },
        {
            "key": "v9Core",
            "name": "v9Core 传统成长",
            "desc": "消费/化工/制造/金融地产链等利润已兑现板块",
            "check": _check_core_common,
        },
        {
            "key": "v9Tech",
            "name": "v9Tech 硬科技替代估值",
            "desc": "半导体/AI硬件/机器人等高研发、利润后置公司",
            "check": _check_tech,
        },
        {
            "key": "v9A1",
            "name": "v9A1 核心质量趋势回踩",
            "desc": "主升浪中的缩量回踩，适合核心仓分批",
            "check": _check_a1,
        },
        {
            "key": "v9A2",
            "name": "v9A2 行业龙头业绩趋势",
            "desc": "行业主线核心资产，适合中线跟踪",
            "check": _check_a2,
        },
        {
            "key": "v9A3",
            "name": "v9A3 防守底仓趋势",
            "desc": "成长波动加大时的组合稳定器",
            "check": _check_a3,
        },
        {
            "key": "v9B1",
            "name": "v9B1 放量平台突破",
            "desc": "硬科技、周期反转、事件催化后的右侧确认",
            "check": _check_b1,
        },
        {
            "key": "v9B2",
            "name": "v9B2 情绪接力",
            "desc": "盘中短线，必须看竞价和板块共振",
            "check": _check_b2,
        },
        {
            "key": "v9S",
            "name": "v9S 小市值弹性",
            "desc": "高弹性波段，仓位≤1/4，严格止损",
            "check": _check_s,
        },
        {
            "key": "v9Screen",
            "name": "v9Screen 综合趋势资金",
            "desc": "非ST/营收同比>0/净利同比>0/主力净流入>0/趋势多头排列/MACD>0",
            "check": _check_screen,
        },
        {
            "key": "v9Low",
            "name": "v9Low 低位修复型",
            "desc": "刚站上中期均线且RSI未极端，估值合理，主力净流入",
            "check": _check_low,
        },
        {
            "key": "v9Stable",
            "name": "v9Stable 稳健型",
            "desc": "大市值/高ROE/估值不过高/经营现金流为正/股息",
            "check": _check_stable,
        },
        {
            "key": "v9Trend",
            "name": "v9Trend 趋势跟随型",
            "desc": "多头排列/MACD>0/主力净流入/业绩正增长/涨幅适中",
            "check": _check_trend,
        },
        {
            "key": "v9Attack",
            "name": "v9Attack 进攻型",
            "desc": "成交活跃与动量，小市值，放量，近5日有涨停，主力净流入",
            "check": _check_attack,
        },
    ]


def check_strategy(strategy_key: str, valid: List[dict], online: Dict[str, Any],
                   indicators: Optional[Dict[str, Any]] = None) -> bool:
    """检查某策略是否命中某股票；可选传入 compute_indicators 产出的外部指标，
    命中时内部复用其 ma*/macd/rsi6，避免重复重算。"""
    for s in get_strategies():
        if s["key"] == strategy_key:
            calc = _calc_indicators_from_rows(valid, indicators)
            try:
                return bool(s["check"](calc, valid, online))
            except Exception:
                return False
    return False


def risk_warnings(valid: List[dict], online: Dict[str, Any],
                  indicators: Optional[Dict[str, Any]] = None) -> List[str]:
    """返回风控提示；indicators 可传外部指标以跳过重复重算"""
    calc = _calc_indicators_from_rows(valid, indicators)
    try:
        return _check_risk(calc, valid, online)
    except Exception:
        return []
