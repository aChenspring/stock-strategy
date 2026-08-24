# -*- coding: utf-8 -*-
"""
策略声明式元数据 + 规则引擎 + 配置存取 + 动态 pipe 计划。

层级模型（自上而下）：
    策略(strategy) -> 复合因子(factor) -> 子因子(rule) -> 基础字段(field)

数据源分层（决定缓存/替换策略）：
    L 本地历史（日K/指标/板块）     end 不变即稳定，快照长期复用
    O 在线接口（财务/估值/资金流）  接口数据会更新，按 TTL 替换缓存
    R 实时盘口（承接/执行位置）     当前用日K涨跌幅代理；接入真盘口后盘中必须重算

设计目标：
    1. 界面可迭代：权重/阈值/开关全部可编辑，保存后扫描与回测即时生效。
    2. 可回测：规则引擎在历史切片上同样可运行（仅依赖 L 类字段）。
    3. 动态 pipe：build_pipe_plan() 按当前策略依赖字段生成
       哪些 key 复用 / 哪些 key 需替换 / 需要新增的 pipe 任务。
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional

# ============ 数据源常量 ============
SRC_LOCAL = "L"
SRC_ONLINE = "O"
SRC_REALTIME = "R"
SRC_LABEL = {SRC_LOCAL: "本地历史", SRC_ONLINE: "在线接口", SRC_REALTIME: "实时盘口"}
SRC_COLOR = {SRC_LOCAL: "#2e7d32", SRC_ONLINE: "#e65100", SRC_REALTIME: "#c62828"}

# 在线接口缓存有效期（小时），超过则下次扫描重新拉取
ONLINE_TTL_HOURS = 6.0

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "strategy_config.json")


# ============ 基础字段注册表（最底层，可被子因子引用） ============
def _f(label: str, source: str, group: str, desc: str = "") -> dict:
    return {"label": label, "source": source, "group": group, "desc": desc}


BASIC_FIELDS: Dict[str, dict] = {
    # ---- 量价（L 本地日K） ----
    "close":         _f("收盘价", SRC_LOCAL, "量价", "当日收盘价(元)"),
    "pct":           _f("涨跌幅", SRC_LOCAL, "量价", "当日涨跌幅(%)"),
    "amount":        _f("成交额", SRC_LOCAL, "量价", "当日成交额(元)"),
    "turnover":      _f("换手率", SRC_LOCAL, "量价", "当日换手率(%)"),
    "volume":        _f("成交量", SRC_LOCAL, "量价", "当日成交量"),
    "amplitude":     _f("振幅", SRC_LOCAL, "量价", "当日振幅(%)"),
    "vol_ratio":     _f("量比", SRC_LOCAL, "量价", "当日量 / 近5日均量"),
    "limit_up_5":    _f("近5日涨停数", SRC_LOCAL, "量价", "近5个交易日涨幅≥阈值天数"),
    "is_break":      _f("突破20日新高", SRC_LOCAL, "量价", "收盘价突破近20日高点"),
    "profit_ratio":  _f("获利盘代理", SRC_LOCAL, "量价", "收盘价在近60日区间的分位"),
    "chg5":          _f("近5日涨幅", SRC_LOCAL, "量价", "近5个交易日累计涨幅(%)"),
    "chg20":         _f("近20日涨幅", SRC_LOCAL, "量价", "近20个交易日累计涨幅(%)"),
    # ---- 均线/技术指标（L，rd zb 或本地自算） ----
    "ma5":           _f("MA5", SRC_LOCAL, "均线", "5日均线"),
    "ma10":          _f("MA10", SRC_LOCAL, "均线", "10日均线"),
    "ma20":          _f("MA20", SRC_LOCAL, "均线", "20日均线"),
    "ma60":          _f("MA60", SRC_LOCAL, "均线", "60日均线"),
    "dev_ma20":      _f("偏离MA20", SRC_LOCAL, "均线", "close/MA20-1"),
    "dev_ma60":      _f("偏离MA60", SRC_LOCAL, "均线", "close/MA60-1"),
    "bull_arrange":  _f("均线多头排列", SRC_LOCAL, "均线", "MA5>MA10>MA20>MA60"),
    "macd":          _f("MACD", SRC_LOCAL, "动量", "MACD柱值"),
    "rsi6":          _f("RSI6", SRC_LOCAL, "动量", "6日相对强弱"),
    "k":             _f("KDJ-K", SRC_LOCAL, "动量", "随机指标K"),
    "d":             _f("KDJ-D", SRC_LOCAL, "动量", "随机指标D"),
    "kd_strong":     _f("KD金叉强势", SRC_LOCAL, "动量", "K>D 且 K>50"),
    "kd_weak":       _f("KD死叉", SRC_LOCAL, "动量", "K<D"),
    # ---- 板块/市场环境（L） ----
    "board_score":   _f("板块环境分", SRC_LOCAL, "环境", "所在板块强弱 0-10"),
    "market_score":  _f("市场环境分", SRC_LOCAL, "环境", "大盘等权强弱 0-10"),
    # ---- 在线接口字段（O） ----
    "main_net":      _f("主力净流入", SRC_ONLINE, "资金", "当日主力净流入(元)"),
    "dde_net":       _f("DDE大单净量", SRC_ONLINE, "资金", "大单净量(元)"),
    "rev_yoy":       _f("营收同比", SRC_ONLINE, "财务", "营业收入同比(%)"),
    "profit_yoy":    _f("净利同比", SRC_ONLINE, "财务", "归母净利润同比(%)"),
    "roe":           _f("ROE", SRC_ONLINE, "财务", "净资产收益率(%)"),
    "pe":            _f("PE", SRC_ONLINE, "估值", "市盈率"),
    "pb":            _f("PB", SRC_ONLINE, "估值", "市净率"),
    # ---- 实时盘口代理（R，当前用 pct 代理） ----
    "order_book_pct": _f("盘口强度", SRC_REALTIME, "盘口", "承接强度代理=当日涨幅"),
    "position_pct":   _f("低吸空间", SRC_REALTIME, "盘口", "距涨停空间代理=当日涨幅"),
}


# ============ 规则算子 ============
def _cmp(value: Any, op: str, target: Any) -> bool:
    """单值比较算子。value 为 None 时一律不命中。"""
    if value is None:
        return False
    try:
        if op == "always":
            return True
        if op == "bool_true":
            return bool(value)
        if op == "bool_false":
            return not bool(value)
        if op == ">":
            return value > target
        if op == ">=":
            return value >= target
        if op == "<":
            return value < target
        if op == "<=":
            return value <= target
        if op == "==":
            return value == target
        if op == "!=":
            return value != target
        if op == "between":
            lo, hi = target[0], target[1]
            return lo <= value <= hi
        if op == "in":
            return value in target
    except (TypeError, ValueError):
        return False
    return False


# ============ 规则/因子定义 ============
def _r(rule_id: str, name: str, field: str, op: str, weight: float,
       value: Any = None, source: str = SRC_LOCAL, group: Optional[str] = None,
       scale: Optional[float] = None, and_cond: Optional[dict] = None,
       desc: str = "") -> dict:
    return {"id": rule_id, "name": name, "field": field, "op": op,
            "value": value, "weight": weight, "source": source,
            "group": group, "scale": scale, "and": and_cond,
            "enabled": True, "desc": desc}


def _and(field: str, op: str, value: Any) -> dict:
    return {"field": field, "op": op, "value": value}


def default_rules() -> Dict[str, List[dict]]:
    """默认子因子规则集。语义与 factors.py 原 14 因子评分完全一致。"""
    return {
        "trend": [
            _r("trend_lag20", "近20日超跌", "chg20", "<", 0.4, -10,
               desc="近20日跌幅>10%（超跌反弹标的）"),
            _r("trend_lag20_d", "深度超跌", "chg20", "<", 0.2, -20,
               desc="近20日跌幅>20%"),
            _r("trend_low60", "60日区间低位", "profit_ratio", "<", 0.2, 0.3,
               desc="收盘价处于近60日区间下1/3"),
            _r("trend_high60", "60日区间高位", "profit_ratio", ">", -0.3, 0.7,
               desc="60日区间高位反指"),
            _r("trend_break", "突破20日新高", "is_break", "bool_true", -0.2,
               desc="追突破反指（均值回归环境）"),
        ],
        "ma_system": [
            _r("ma_below20", "MA20下方超跌", "dev_ma20", "between", 0.4, [-0.25, 0],
               desc="收盘价在MA20下方25%~0%（超跌未崩）"),
            _r("ma_back20", "刚站回MA20", "dev_ma20", "between", 0.2, [0, 0.08],
               desc="收盘价刚站回MA20上方8%内"),
            _r("ma_arrange", "均线多头排列", "bull_arrange", "bool_true", -0.3,
               desc="多头排列反指（均值回归环境）"),
            _r("ma_below60", "低于MA60", "dev_ma60", "<", 0.1, 0,
               desc="收盘价低于MA60（低位修复）"),
        ],
        "volume": [
            _r("vol_turnover_low", "低换手<2%", "turnover", "<", 0.4, 2,
               desc="当日换手率<2%（缩量企稳）"),
            _r("vol_turnover_mid", "换手2-5%", "turnover", "between", 0.2, [2, 5],
               desc="当日换手率2~5%"),
            _r("vol_turnover_high", "高换手>10%", "turnover", ">", -0.3, 10,
               desc="高换手反指（分歧过大）"),
            _r("vol_ratio_low", "量比<1.2", "vol_ratio", "<", 0.2, 1.2,
               desc="量比<1.2（未放量）"),
            _r("vol_ratio_hot", "量比>2.5", "vol_ratio", ">", -0.3, 2.5,
               desc="放量反指"),
        ],
        "main_flow": [
            _r("mf_positive", "主力净流入", "main_net", ">", 0.6, 0,
               source=SRC_ONLINE, desc="当日主力净流入>0"),
            _r("mf_big", "净流入超1亿", "main_net", ">", 0.3, 1e8,
               source=SRC_ONLINE, desc="当日主力净流入>1亿元"),
            _r("mf_negative", "主力净流出", "main_net", "<", 0.2, 0,
               source=SRC_ONLINE, desc="当日主力净流入<0"),
        ],
        "dde": [
            _r("dde_big", "DDE超1亿", "dde_net", ">", 0.9, 1e8,
               source=SRC_ONLINE, group="dde", desc="DDE大单净量>1亿元"),
            _r("dde_pos", "DDE净流入", "dde_net", ">", 0.6, 0,
               source=SRC_ONLINE, group="dde", desc="DDE大单净量>0"),
            _r("dde_neg", "DDE净流出", "dde_net", "<", 0.2, 0,
               source=SRC_ONLINE, group="dde", desc="DDE大单净量<0"),
        ],
        "momentum": [
            _r("mom_pct_ok", "当日0-6%", "pct", "between", 0.4, [0, 6],
               desc="当日涨0~6%（企稳转强）"),
            _r("mom_pct_strong", "当日2-6%", "pct", "between", 0.2, [2, 6],
               desc="当日涨2~6%（明显走强）"),
            _r("mom_pct_fall", "当日跌超3%", "pct", "<", -0.3, -3,
               desc="当日跌幅>3%回避"),
            _r("mom_kd_strong", "KD金叉强势", "kd_strong", "bool_true", 0.2,
               desc="K>D 且 K>50"),
            _r("mom_rsi_low", "RSI6低位企稳", "rsi6", "between", 0.1, [20, 55],
               desc="RSI6处于20~55（低位未钝化）"),
            _r("mom_chg5", "5日企稳", "chg5", "between", 0.2, [0, 10],
               desc="近5日涨幅0~10%（低位修复启动）"),
        ],
        "volatility": [
            _r("vol_amp_low", "振幅<8%", "amplitude", "<", 0.4, 8,
               desc="当日振幅<8%（低波动企稳）"),
            _r("vol_amp_mid", "振幅8-12%", "amplitude", "between", 0.2, [8, 12],
               desc="当日振幅8~12%"),
            _r("vol_amp_high", "振幅>15%", "amplitude", ">", -0.3, 15,
               desc="剧烈波动反指"),
        ],
        "board": [
            _r("board_score", "板块环境强弱", "board_score", ">", 1.0, 0,
               scale=5.0, desc="板块环境分/5 线性映射 0-10"),
        ],
        "growth": [
            _r("g_profit_pos", "净利正增长", "profit_yoy", ">", 0.5, 0,
               source=SRC_ONLINE, desc="归母净利润同比>0"),
            _r("g_profit_big", "净利增>20%", "profit_yoy", ">", 0.2, 20,
               source=SRC_ONLINE, desc="归母净利润同比>20%"),
            _r("g_rev_pos", "营收正增长", "rev_yoy", ">", 0.3, 0,
               source=SRC_ONLINE, desc="营业收入同比>0"),
            _r("g_rev_big", "营收增>15%", "rev_yoy", ">", 0.1, 15,
               source=SRC_ONLINE, desc="营业收入同比>15%"),
            _r("g_fallback", "双降微利", "rev_yoy", "<=", 0.1, 0,
               source=SRC_ONLINE, and_cond=_and("profit_yoy", "<", 0),
               desc="营收无增长且净利下滑时微利"),
        ],
        "valuation": [
            _r("val_pb_low", "破净", "pb", "<", 0.6, 1,
               source=SRC_ONLINE, group="val_pe", and_cond=_and("pe", ">", 0),
               desc="PE>0 且 PB<1"),
            _r("val_pe_low", "PE<40", "pe", "<", 0.5, 40,
               source=SRC_ONLINE, group="val_pe", and_cond=_and("pe", ">", 0),
               desc="PE 处于 0-40"),
            _r("val_pe_mid", "PE<80", "pe", "<", 0.3, 80,
               source=SRC_ONLINE, group="val_pe", and_cond=_and("pe", ">", 0),
               desc="PE 处于 40-80"),
            _r("val_pe_high", "PE<180", "pe", "<", 0.2, 180,
               source=SRC_ONLINE, group="val_pe", and_cond=_and("pe", ">", 0),
               desc="PE 处于 80-180"),
            _r("val_pe_neg", "PE为负", "pe", "<", 0.1, 0,
               source=SRC_ONLINE, group="val_pe", desc="亏损股微利"),
        ],
        "theme": [
            _r("theme_score", "题材催化", "board_score", "always", 1.0, None,
               scale=5.0, desc="板块涨幅代理题材强度"),
        ],
        "order_book": [
            _r("ob_limit", "涨停", "order_book_pct", ">=", 0.8, 9.5,
               source=SRC_REALTIME, group="ob", desc="涨幅≥9.5% 承接强"),
            _r("ob_strong", "大涨", "order_book_pct", ">=", 0.6, 5,
               source=SRC_REALTIME, group="ob", desc="涨幅≥5%"),
            _r("ob_pos", "收涨", "order_book_pct", ">", 0.4, 0,
               source=SRC_REALTIME, group="ob", desc="涨幅>0%"),
            _r("ob_else", "收跌", "order_book_pct", "<=", 0.1, 0,
               source=SRC_REALTIME, group="ob", desc="涨幅≤0%"),
        ],
        "position": [
            _r("pos_ok", "低吸空间大", "position_pct", "<", 0.7, 5,
               source=SRC_REALTIME, group="pos", desc="涨幅<5% 可低吸"),
            _r("pos_mid", "低吸空间中", "position_pct", "<", 0.4, 9,
               source=SRC_REALTIME, group="pos", desc="涨幅<9%"),
            _r("pos_else", "难低吸", "position_pct", ">=", 0.1, 9,
               source=SRC_REALTIME, group="pos", desc="涨幅≥9% 已难低吸"),
        ],
        "market": [
            _r("market_score", "市场环境强弱", "market_score", "always", 1.0, None,
               scale=10.0, desc="市场环境分/10 线性映射 0-10"),
        ],
    }


DEFAULT_FACTOR_DEFS: List[dict] = [
    {"key": "trend",     "name": "趋势结构",   "weight": 0.05, "source": SRC_LOCAL,    "desc": "涨停/突破/多头排列等趋势信号"},
    {"key": "ma_system", "name": "均线系统",   "weight": 0.05, "source": SRC_LOCAL,    "desc": "多头排列与对60日线的合理偏离"},
    {"key": "volume",    "name": "量能活跃",   "weight": 0.05, "source": SRC_LOCAL,    "desc": "成交额/换手/量比反映活跃度"},
    {"key": "main_flow", "name": "主力行为",   "weight": 0.05, "source": SRC_ONLINE,   "desc": "主力资金净流入强度"},
    {"key": "dde",       "name": "DDE大单",    "weight": 0.05, "source": SRC_ONLINE,   "desc": "大单净量方向与强度"},
    {"key": "momentum",  "name": "动量指标",   "weight": 0.05, "source": SRC_LOCAL,    "desc": "RSI/KDJ 反映短线动量"},
    {"key": "volatility","name": "波动风险",   "weight": 0.05, "source": SRC_LOCAL,    "desc": "振幅低则波动风险小"},
    {"key": "board",     "name": "板块环境",   "weight": 0.05, "source": SRC_LOCAL,    "desc": "所处板块相对强弱", "neutral": 0.5, "backtestable": False},
    {"key": "growth",    "name": "基本面增长", "weight": 0.05, "source": SRC_ONLINE,   "desc": "营收/净利同比增速"},
    {"key": "valuation", "name": "估值水平",   "weight": 0.05, "source": SRC_ONLINE,   "desc": "PE/PB 估值分档"},
    {"key": "theme",     "name": "题材催化",   "weight": 0.05, "source": SRC_LOCAL,    "desc": "板块涨幅代理题材强度", "backtestable": False},
    {"key": "order_book","name": "盘口承接",   "weight": 0.05, "source": SRC_REALTIME, "desc": "承接强度（当前以涨幅代理）"},
    {"key": "position",  "name": "执行位置",   "weight": 0.05, "source": SRC_REALTIME, "desc": "低吸空间（当前以涨幅代理）"},
    {"key": "market",    "name": "市场环境",   "weight": 0.05, "source": SRC_LOCAL,    "desc": "大盘等权强弱", "backtestable": False},
]

# 扫描策略注册表：factor_default 为可编辑综合因子策略，其余为 v9 硬条件策略
# v9 策略的硬条件字段来源仅作展示与 pipe 计划分析
V9_STRATEGIES = [
    {"key": "v9Core",   "name": "v9Core 传统成长", "source": SRC_ONLINE,
     "desc": "消费/化工/制造/金融地产链等利润已兑现板块（ROE>8/PE<60/净利增>20%或营收增>15%）"},
    {"key": "v9Tech",   "name": "v9Tech 硬科技替代估值", "source": SRC_ONLINE,
     "desc": "半导体/AI硬件/机器人等高研发利润后置（PS≤35或PB≤12或PE≤180）"},
    {"key": "v9A1",     "name": "v9A1 核心质量趋势回踩", "source": SRC_LOCAL,
     "desc": "MA20>MA60且收盘在MA20上方-2%~12%（本地量价可测）"},
    {"key": "v9A2",     "name": "v9A2 行业龙头业绩趋势", "source": SRC_ONLINE,
     "desc": "市值>300亿/ROE>8/净利增>15/多头排列"},
    {"key": "v9A3",     "name": "v9A3 防守底仓趋势", "source": SRC_ONLINE,
     "desc": "负债<50/现金流>0/ROE>8/PE<40/股息>2/趋势多头"},
    {"key": "v9B1",     "name": "v9B1 放量平台突破", "source": SRC_LOCAL,
     "desc": "突破20日高点/量比>2/换手3-25/成交>5亿/涨幅>3%（本地量价可测）"},
    {"key": "v9B2",     "name": "v9B2 情绪接力", "source": SRC_LOCAL,
     "desc": "近20日有涨停/当日涨幅>7/量比>1.5/换手>3（本地量价可测）"},
    {"key": "v9S",      "name": "v9S 小市值弹性", "source": SRC_ONLINE,
     "desc": "市值<200亿/净利增>30且营收增>20/突破20日高点"},
    {"key": "v9Screen", "name": "v9Screen 综合趋势资金", "source": SRC_LOCAL,
     "desc": "非ST/多头排列/MACD>0/营收净利增>0/主力净流入>0"},
    {"key": "v9Low",    "name": "v9Low 低位修复型", "source": SRC_ONLINE,
     "desc": "刚站上中期均线/RSI未极端/主力净流入/估值合理"},
    {"key": "v9Stable", "name": "v9Stable 稳健型", "source": SRC_ONLINE,
     "desc": "市值>500亿/ROE>10/负债<50/现金流>0/PE<30/PB<3/股息>1.5"},
    {"key": "v9Trend",  "name": "v9Trend 趋势跟随型", "source": SRC_ONLINE,
     "desc": "多头排列/MACD>0/主力净流入/业绩正增长/20日涨幅5-30"},
    {"key": "v9Attack", "name": "v9Attack 进攻型", "source": SRC_ONLINE,
     "desc": "近5日涨停/量比>1.5/换手>3/主力净流入/市值<300亿/净利增>0"},
    {"key": "v9Limit5", "name": "v9Limit5 连板启动前一日", "source": SRC_LOCAL,
     "desc": "涨停基因（近20日涨停≥2/近60日≥8/距上次涨停≤45日）+站上MA20（偏离0~25%）/不深破MA60/市值≤100亿（本地量价可测）"},
]

DEFAULT_FACTOR_WEIGHTS = {f["key"]: f["weight"] for f in DEFAULT_FACTOR_DEFS}


# ============ 规则引擎 ============
def eval_rule(rule: dict, ctx: Dict[str, Any]) -> bool:
    """评估单条子因子规则是否命中。"""
    if not rule.get("enabled", True):
        return False
    hit = _cmp(ctx.get(rule["field"]), rule.get("op", ">"),
               rule.get("value"))
    if hit and rule.get("and"):
        a = rule["and"]
        hit = _cmp(ctx.get(a.get("field")), a.get("op", ">"), a.get("value"))
    return hit


def score_factor(fdef: Dict[str, Any], ctx: Dict[str, Any],
                 rules: Optional[List[dict]] = None) -> float:
    """计算一个复合因子的 0-10 分。

    - 阶梯规则（同 group）：按顺序命中即停止，只取第一个命中的权重。
    - 连续规则（scale）：命中后贡献 = weight * clamp01(ctx[field]/scale)。
    - 全部未命中：给 neutral*10（默认 0）。
    - 归一：clamp01(Σ命中权重) * 10（与原 factors.py 语义一致）。
    """
    if not fdef.get("enabled", True):
        return 0.0
    rls = rules if rules is not None else default_rules().get(fdef["key"], [])
    total = 0.0
    hit_groups = set()
    for r in rls:
        if not r.get("enabled", True):
            continue
        grp = r.get("group")
        if grp and grp in hit_groups:
            continue
        if eval_rule(r, ctx):
            w = r.get("weight", 0.0)
            if r.get("scale"):
                v = ctx.get(r["field"])
                ratio = _clamp01((v or 0.0) / r["scale"])
                total += w * ratio
            else:
                total += w
            if grp:
                hit_groups.add(grp)
    if total == 0.0 and fdef.get("neutral"):
        return _clamp01(fdef["neutral"]) * 10.0
    return _clamp01(total) * 10.0


def score_factor_set(factor_defs: List[dict], ctx: Dict[str, Any],
                     rules_map: Optional[Dict[str, List[dict]]] = None,
                     active_sources: Optional[set] = None,
                     online_empty: bool = False) -> Dict[str, float]:
    """按配置计算全部复合因子分。active_sources 用于回测只算本地因子；
    online_empty 为 True（在线数据整体不可用）时，在线/实时因子给中性分
    （默认 5 分），避免 0 分稀释综合分导致小资金 min_score 门槛下漏选。"""
    rmap = rules_map if rules_map is not None else default_rules()
    scores = {}
    for f in factor_defs:
        src = f.get("source")
        if active_sources is not None and src not in active_sources:
            scores[f["key"]] = 0.0
            continue
        if online_empty and src in (SRC_ONLINE, SRC_REALTIME):
            scores[f["key"]] = f.get("neutral", 0.5) * 10.0
            continue
        scores[f["key"]] = score_factor(f, ctx, rmap.get(f["key"]))
    return scores


def total_score(factor_defs: List[dict], scores: Dict[str, float]) -> float:
    """按启用因子权重归一化合成 0-100 综合分。"""
    wsum = sum(f["weight"] for f in factor_defs if f.get("enabled", True)) or 1.0
    total = sum(scores.get(f["key"], 0.0) * f["weight"]
                for f in factor_defs if f.get("enabled", True))
    return total / wsum * 10.0


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


# ============ 配置存取（用户可迭代覆盖，保存到本地 JSON） ============
def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = copy.deepcopy(base)
        for k, v in override.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
        return out
    return copy.deepcopy(override)


def build_factor_defs(cfg: Optional[dict] = None) -> List[dict]:
    """由配置构建复合因子定义列表（含用户权重/开关覆盖）。"""
    defs = copy.deepcopy(DEFAULT_FACTOR_DEFS)
    if not cfg:
        return defs
    fw = cfg.get("factor_weights") or {}
    fe = cfg.get("factor_enabled") or {}
    for f in defs:
        if f["key"] in fw:
            w = fw[f["key"]]
            f["weight"] = max(0.0, float(w)) if w is not None else f["weight"]
        if f["key"] in fe:
            f["enabled"] = bool(fe[f["key"]])
    return defs


def build_rules_map(cfg: Optional[dict] = None) -> Dict[str, List[dict]]:
    """由配置构建子因子规则集（用户编辑的规则覆盖默认）。"""
    base = default_rules()
    if not cfg:
        return base
    user_rules = cfg.get("rules") or {}
    out = {}
    for key, rules in base.items():
        ur = user_rules.get(key)
        if not ur:
            out[key] = rules
            continue
        merged = []
        by_id = {r["id"]: r for r in rules}
        for urule in ur:
            rid = urule.get("id")
            if rid in by_id:
                m = copy.deepcopy(by_id[rid])
                for k, v in urule.items():
                    if k in ("id", "field", "source", "group", "and"):
                        continue  # 结构字段不允许 UI 改
                    m[k] = copy.deepcopy(v)
                merged.append(m)
            else:
                merged.append(copy.deepcopy(urule))
        out[key] = merged
    return out


def load_strategy_config() -> dict:
    """加载用户配置（不存在则返回空 dict，行为=默认）。"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_strategy_config(cfg: dict) -> bool:
    """保存用户配置到本地 JSON。"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(cfg, fp, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def reset_strategy_config() -> bool:
    """删除用户配置，恢复默认。"""
    try:
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
        return True
    except Exception:
        return False


# ============ 动态 pipe 计划（数据源感知，决定 key 替换策略） ============
def collect_used_fields(strategy_key: str, cfg: Optional[dict] = None) -> Dict[str, set]:
    """收集当前策略实际使用的全部基础字段，按来源分组。

    返回 {"L": {field...}, "O": {...}, "R": {...}}
    """
    used: Dict[str, set] = {SRC_LOCAL: set(), SRC_ONLINE: set(), SRC_REALTIME: set()}
    rmap = build_rules_map(cfg)

    if strategy_key == "factor_default":
        defs = build_factor_defs(cfg)
        for f in defs:
            if not f.get("enabled", True):
                continue
            src = f.get("source")
            for r in rmap.get(f["key"], []):
                if not r.get("enabled", True):
                    continue
                used[src].add(r["field"])
                if r.get("and"):
                    used[src].add(r["and"].get("field"))
        return used

    # v9 硬条件策略：按其依赖的在线/本地字段粗粒度分组
    for s in V9_STRATEGIES:
        if s["key"] == strategy_key:
            used[s["source"]].add(s["key"])
            if s["source"] == SRC_ONLINE:
                used[SRC_LOCAL].update({"close", "ma20", "ma60"})
            else:
                used[SRC_LOCAL].update({"close", "ma20", "ma60", "macd", "vol"})
            return used
    return used


def build_pipe_plan(strategy_key: str, cfg: Optional[dict] = None) -> dict:
    """生成数据源感知的 pipe 计划（哪些 key 复用/替换/新增）。

    返回 {
      "groups": {"L": {fields, action, note}, "O": {...}, "R": {...}},
      "reuse":  [key 说明...],
      "replace":[key 说明...],
      "add":    [新增 pipe 任务...],
      "used_fields": {...}
    }
    """
    used = collect_used_fields(strategy_key, cfg)
    groups = {
        SRC_LOCAL: {
            "label": SRC_LABEL[SRC_LOCAL], "color": SRC_COLOR[SRC_LOCAL],
            "fields": sorted(used[SRC_LOCAL]),
            "action": "复用（end 不变即稳定，快照/指标缓存长期可用）",
        },
        SRC_ONLINE: {
            "label": SRC_LABEL[SRC_ONLINE], "color": SRC_COLOR[SRC_ONLINE],
            "fields": sorted(used[SRC_ONLINE]),
            "action": f"按 TTL({ONLINE_TTL_HOURS:.0f}h) 替换缓存，下次扫描重拉",
        },
        SRC_REALTIME: {
            "label": SRC_LABEL[SRC_REALTIME], "color": SRC_COLOR[SRC_REALTIME],
            "fields": sorted(used[SRC_REALTIME]),
            "action": "盘中必须重算（当前为日K涨幅代理，接入真盘口后替换）",
        },
    }
    reuse = []
    replace = []
    add = []
    if strategy_key == "factor_default":
        for f in build_factor_defs(cfg):
            if not f.get("enabled", True):
                continue
            src = f.get("source")
            if src == SRC_LOCAL:
                reuse.append(f"{f['name']}（本地，快照可复用）")
            elif src == SRC_ONLINE:
                replace.append(f"{f['name']}（在线，{ONLINE_TTL_HOURS:.0f}h 内复用，超期重拉）")
            else:
                add.append(f"{f['name']}（实时，动态 pipe 插入盘口重算任务）")
    else:
        for s in V9_STRATEGIES:
            if s["key"] == strategy_key:
                if s["source"] == SRC_ONLINE:
                    replace.append(f"{s['name']} 的在线硬条件（财务/估值/资金流，按 TTL 替换）")
                    reuse.append(f"{s['name']} 的本地硬条件（K线/指标，复用）")
                else:
                    reuse.append(f"{s['name']} 全部条件均为本地数据，可复用")
                break
    return {"groups": groups, "reuse": reuse, "replace": replace,
            "add": add, "used_fields": used}


# ============ 快照条目的字段来源标记（快速过滤时效提示用） ============
def snapshot_freshness(item: dict, cfg: Optional[dict] = None) -> dict:
    """判断快照条目的新鲜度：哪些来源超期/需重算。"""
    full = item.get("full") or {}
    factors = item.get("factor_scores") or {}
    has_stale = False
    has_realtime = False
    for key in factors:
        if key in ("order_book", "position"):
            has_realtime = True
        elif key in ("main_flow", "dde", "growth", "valuation"):
            has_stale = True
    return {"has_stale": has_stale, "has_realtime": has_realtime}
