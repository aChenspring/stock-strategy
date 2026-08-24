
# -*- coding: utf-8 -*-
"""
策略数据层：行情加载、板块、指标、在线财务/估值/资金流，全部带缓存。
使用 stock_sdk 的 rd / bk / zb + 在线接口。
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from math import isfinite
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timedelta

from stock_sdk import rd, bk, zb, get_fundamentals, query, cash_flow, get_valuation, get_money_flow

# ============ 配置 ============
# 沪深A股 + 北交所920（股票池，不含基金/债券）
A_SHARE_PREFIXES = ["0*", "3*", "6*", "920*"]

# 本地数据库表名（./mydb 私有存储）
TABLE_CACHE = "策略缓存"          # code:date -> dict（在线数据缓存）


def _nearest_trade_date(dt: datetime) -> str:
    """简单推算最近交易日（周末回退到周五，忽略节假日）。"""
    weekday = dt.weekday()
    if weekday >= 5:  # 周六、周日
        dt -= timedelta(days=weekday - 4)
    return dt.strftime("%Y%m%d")


def shift_days(date_str: str, days: int) -> str:
    """按自然日平移日期（YYYYMMDD -> YYYYMMDD）。"""
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
    except Exception:
        dt = datetime.strptime(END, "%Y%m%d")
    return (dt + timedelta(days=days)).strftime("%Y%m%d")


def shift_months(date_str: str, months: int) -> str:
    """按自然月平移日期，日末按该月最后一天裁剪。"""
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
    except Exception:
        dt = datetime.strptime(END, "%Y%m%d")
    year = dt.year
    month = dt.month + months
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    max_day = [31, 29 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 28,
               31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    day = min(dt.day, max_day)
    return f"{year:04d}{month:02d}{day:02d}"


def calc_window_start(end_date: str, window: str) -> str:
    """根据窗口描述计算起始日期。

    扫描窗口（自然月/年）: 3m, 6m, 1y, 2y
    回测窗口（交易日数，按 1 交易日≈1.6 自然日估算）: 30, 60, 120, 250, 500
    """
    if not end_date:
        end_date = END
    w = str(window).strip().lower()
    if w.endswith("m"):
        return shift_months(end_date, -int(w[:-1]))
    if w.endswith("y"):
        return shift_months(end_date, -int(w[:-1]) * 12)
    if w.isdigit():
        return shift_days(end_date, -int(w) * 2)
    return shift_months(end_date, -6)


def calc_backtest_pre_start(end_date: str, window: str, pre_days: int = 60) -> tuple:
    """回测用：根据结束日期、回测窗口和预热天数，计算回测起始日期与指标预计算起始日期。"""
    bt_start = calc_window_start(end_date, window)
    pre_start = shift_days(bt_start, -pre_days * 2)
    return bt_start, pre_start


_today = datetime.now()
# 默认数据范围：最近 6 个月到最近交易日（rd.vals 会自动截断到实际最新数据）
START = (_today - timedelta(days=180)).strftime("%Y%m%d")
END = _nearest_trade_date(_today)


# ============ 工具函数 ============
def _finite(value) -> Optional[float]:
    """安全转换为有限浮点数，无效返回 None"""
    try:
        v = float(value)
        return v if isfinite(v) else None
    except (TypeError, ValueError):
        return None


def require_online_result(value):
    """检查在线接口返回的错误字典"""
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(value["error"])
    return value


# ============ 行情加载（带缓存） ============
class MarketCache:
    """内存 + ./mydb 双层缓存"""

    def __init__(self):
        self._mem: Dict[str, Any] = {}

    def _key(self, *parts) -> str:
        return ":".join(str(p) for p in parts)

    # ---------- 内存缓存 ----------
    def mem_get(self, key: str):
        return self._mem.get(key)

    def mem_set(self, key: str, value):
        self._mem[key] = value

    # ---------- ./mydb 持久化缓存（在线数据） ----------
    def db_get(self, table: str, code: str, date: str):
        try:
            row = rd.get(table, code, date)
            if isinstance(row, dict):
                return row
        except Exception:
            pass
        return None

    def db_set(self, table: str, code: str, date: str, value: dict):
        try:
            rd.set(table, code, date, value).do()
        except Exception:
            pass

    # ---------- 批量写入用 Pipe ----------
    def db_mset(self, table: str, items: List[tuple]):
        """items: [(code, date, value), ...]"""
        try:
            pipe = rd.pipe()
            for code, date, value in items:
                pipe.mset(table, code, date, value)
            pipe.do()
        except Exception:
            pass


# ============ 行情批量加载 ============
def load_market_rows(prefixes: List[str] = A_SHARE_PREFIXES,
                     start: str = START, end: str = END) -> Dict[str, List[dict]]:
    """
    按前缀批量加载日K，返回 {code: [rows...]}（时间升序，前复权）
    使用 rd 前缀服务端查询，不逐股请求。
    """
    rows: List[dict] = []
    for prefix in prefixes:
        try:
            part = rd.vals("日k", prefix, f"{start}<{end}").do()
            rows.extend(part)
        except Exception:
            continue

    rows_by_code: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", ""))
        if len(code) != 6 or not code.isdigit():
            continue
        rows_by_code[code].append(row)

    for values in rows_by_code.values():
        values.sort(key=lambda r: int(r.get("date", 0)))
    return rows_by_code


# ============ 有效交易记录过滤 ============
def valid_trading_rows(rows: List[dict]) -> List[dict]:
    """排除停牌/无效记录"""
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        close = _finite(row.get("close"))
        if close is None or close <= 0:
            continue
        if "pct_chg" in row:
            pct = row.get("pct_chg")
            if pct in ("-", None, ""):
                continue
            if _finite(pct) is None:
                continue
        if "volume" in row:
            if _finite(row.get("volume")) is None:
                continue
        result.append(row)
    return sorted(result, key=lambda r: int(r.get("date", 0)))


# ============ 在线数据加载（带缓存） ============
# 财务字段别名（兼容不同接口字段命名）
_FUND_ALIASES = {
    "pe_ratio": ("pe_ratio", "pe_ttm"),
    "pb_ratio": ("pb_ratio", "pb"),
    "ps_ratio": ("ps_ratio",),
    "roe": ("roe", "roe_weighted"),
    "debt_to_assets": ("debt_to_assets", "debt_ratio"),
    "net_profit_margin": ("net_profit_margin", "net_margin"),
    "gross_margin": ("gross_margin", "gross_profit_margin", "gross_margin_rate"),
    "revenue": ("total_operating_revenue", "total_revenue", "revenue", "operating_revenue"),
    "revenue_yoy": ("revenue_yoy", "total_operating_revenue_yoy", "operating_revenue_yoy"),
    "net_profit": ("net_profit", "total_profit", "net_profit_attr"),
    "profit_yoy": ("profit_yoy", "net_profit_yoy", "total_profit_yoy"),
    "deducted_profit": ("deducted_profit", "deducted_net_profit", "net_profit_deducted"),
    "deducted_yoy": ("deducted_yoy", "deducted_net_profit_yoy"),
    "eps": ("eps", "basic_eps"),
    "bps": ("bps", "book_value_per_share", "net_assets_per_share"),
    "operating_cash_flow": ("operating_cash_flow", "net_operating_cash_flow"),
    "rd_expense": ("rd_expense", "research_expense", "rd_cost"),
    "dividend_yield": ("dividend_yield", "dy_rate"),
}


def _extract_fund(item: dict) -> dict:
    """从单条财务记录中提取需要字段。"""
    result = {}
    for alias, names in _FUND_ALIASES.items():
        for n in names:
            if n in item:
                result[alias] = item[n]
                break
    return result


class OnlineData:
    """在线财务/估值/资金流，带 ./mydb 缓存"""

    def __init__(self, cache: MarketCache):
        self.cache = cache
        self._mem = {}
        self._fail_streak = 0
        self._online_dead = False  # 在线数据整体不可用（返回空），本次扫描内短路请求
        self._lock = threading.Lock()

    # 在线接口失败熔断：连续失败 FAIL_LIMIT 次后，本次扫描内直接跳过在线请求，
    # 避免在接口不可用时每只股票都白白等待网络超时。
    FAIL_LIMIT = 3

    def _circuit_open(self) -> bool:
        with self._lock:
            return self._fail_streak >= self.FAIL_LIMIT

    def _available(self) -> bool:
        """在线请求是否可用：熔断未打开 且 未标记在线整体空数据。"""
        with self._lock:
            return not (self._fail_streak >= self.FAIL_LIMIT or self._online_dead)

    def probe_online(self, codes: List[str], max_samples: int = 2) -> bool:
        """采样探测在线数据是否整体可用。

        在线接口返回空列表（而非异常）时熔断不会触发，会导致每只股票都
        白白发起在线请求。本方法抽查少量股票的估值/资金流：若全部无数据，
        标记 ``_online_dead`` 短路本次扫描内的所有在线请求（切换纯本地评分）。
        返回 True 表示在线可用（至少一只股票有任一在线数据）。"""
        if self._online_dead or self._circuit_open():
            return False
        for code in codes[:max_samples]:
            try:
                if self.valuation(code) or self.money_flow(code, days=5):
                    return True
            except Exception:
                pass
        with self._lock:
            self._online_dead = True
        return False

    def _mark_ok(self):
        with self._lock:
            self._fail_streak = 0

    def _mark_fail(self):
        with self._lock:
            self._fail_streak += 1

    def _get_cached(self, kind: str, code: str, date: str) -> Optional[dict]:
        key = f"{kind}:{code}:{date}"
        with self._lock:
            if key in self._mem:
                return self._mem[key]
        row = self.cache.db_get(TABLE_CACHE, code, f"{date}:{kind}")
        if row:
            with self._lock:
                self._mem[key] = row
            return row
        return None

    def _set_cached(self, kind: str, code: str, date: str, value: dict):
        key = f"{kind}:{code}:{date}"
        with self._lock:
            self._mem[key] = value
        self.cache.db_set(TABLE_CACHE, code, f"{date}:{kind}", value)

    def prewarm(self, kind_dates: List[tuple], codes: List[str]) -> None:
        """rd.pipe 批量读取本地缓存并预热内存。

        ``kind_dates`` 为 [(kind, date), ...]，date 必须与对应接口的缓存键
        一致（如 money_flow 用 days 作键 -> ("flow", "5")，valuation -> ("val", "latest")）。
        评分循环会对每只股票调用 valuation/money_flow，其中逐条 db_get
        是典型的“多个离散精确键”场景。批量 mget 一次拉取后，循环内
        全部内存命中，不再逐条访问 ./mydb。
        """
        if not codes or not kind_dates:
            return
        try:
            pipe = rd.pipe()
            keys: List[tuple] = []
            for code in codes:
                for kind, date in kind_dates:
                    pipe.mget(TABLE_CACHE, code, f"{date}:{kind}")
                    keys.append((kind, code, date))
            rows = pipe.do()
            if isinstance(rows, dict):
                rows = [rows]
            with self._lock:
                for (kind, code, date), row in zip(keys, rows):
                    if isinstance(row, dict):
                        self._mem.setdefault(f"{kind}:{code}:{date}", row)
        except Exception:
            pass

    def _stock_suffix(self, code: str) -> str:
        """转换为带交易所后缀的代码格式"""
        if code.startswith(("6", "9", "5")):
            return f"{code}.XSHG"
        return f"{code}.XSHE"

    def fundamentals(self, code: str, stat_date: str = "") -> Optional[dict]:
        """财务数据：ROE/负债/净利增速/营收增速/经营现金流/股息率等"""
        if not self._available():
            return None
        cached = self._get_cached("fund", code, stat_date or "latest")
        if cached:
            return cached

        try:
            q = query(cash_flow).filter(cash_flow.code == self._stock_suffix(code))
            if stat_date:
                data = require_online_result(get_fundamentals(q, statDate=stat_date))
            else:
                data = require_online_result(get_fundamentals(q))
            result = {}
            if isinstance(data, list) and data:
                item = data[-1] if isinstance(data[-1], dict) else {}
                result = _extract_fund(item)
            self._set_cached("fund", code, stat_date or "latest", result)
            self._mark_ok()
            return result or None
        except Exception:
            self._mark_fail()
            return None

    def fundamentals_batch(self, codes: List[str], batch: int = 100, stat_date: str = "") -> Dict[str, dict]:
        """批量查询财务数据，减少在线请求次数。

        查询结果写入内存缓存，后续 ``fundamentals(code)`` 直接命中。
        接口不可用（熔断/异常）时静默跳过，不影响本地扫描。
        """
        if not codes or not self._available():
            return {}
        out: Dict[str, dict] = {}
        codes = [c for c in codes if not self._get_cached("fund", c, stat_date or "latest")]
        persist: List[tuple] = []  # (code, date_key, value)，结束后 Pipe 批量持久化
        date_key = stat_date or "latest"
        for i in range(0, len(codes), batch):
            chunk = codes[i:i + batch]
            if not chunk:
                continue
            try:
                q = query(cash_flow).filter(
                    cash_flow.code.in_([self._stock_suffix(c) for c in chunk])
                )
                data = require_online_result(
                    get_fundamentals(q, statDate=stat_date) if stat_date else get_fundamentals(q)
                )
                # 按股票代码分组，取每只最新一条
                by_code: Dict[str, list] = defaultdict(list)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            c = item.get("code", "")
                            by_code[c].append(item)
                for raw in chunk:
                    sfx = self._stock_suffix(raw)
                    items = by_code.get(sfx) or by_code.get(raw) or []
                    if items:
                        d = _extract_fund(items[-1])
                        key = f"fund:{raw}:{date_key}"
                        with self._lock:
                            self._mem[key] = d
                        persist.append((raw, f"{date_key}:fund", d))
                        out[raw] = d
                self._mark_ok()
            except Exception:
                self._mark_fail()
        if persist:
            self.cache.db_mset(TABLE_CACHE, persist)
        return out

    def valuation(self, code: str, date: str = "") -> Optional[dict]:
        """估值数据：PE/PB/PS/市值"""
        if not self._available():
            return None
        cached = self._get_cached("val", code, date or "latest")
        if cached:
            return cached
        try:
            data = require_online_result(get_valuation(
                self._stock_suffix(code), date=date or None
            ))
            result = {}
            if isinstance(data, list) and data:
                item = data[-1] if isinstance(data[-1], dict) else {}
                for f in ("pe_ratio", "pb_ratio", "ps_ratio",
                          "market_cap", "turnover_ratio"):
                    if f in item:
                        result[f] = item[f]
            self._set_cached("val", code, date or "latest", result)
            self._mark_ok()
            return result or None
        except Exception:
            self._mark_fail()
            return None

    def money_flow(self, code: str, days: int = 10) -> Optional[dict]:
        """资金流：主力净流入/DDE大单/增仓占比。

        返回字段中同时包含最新一个交易日的单日和近 ``days`` 日汇总，
        满足按最新交易日（如 20260820）口径过滤以及原有评分的需求。
        """
        if not self._available():
            return None
        cached = self._get_cached("flow", code, str(days))
        if cached:
            return cached
        try:
            data = require_online_result(get_money_flow(
                self._stock_suffix(code), days=days
            ))
            def _gather(item: dict, keyword: str) -> float:
                """累加 item 中所有含 keyword（且不含 net/rate）的字段，用于流入/流出。"""
                total = 0.0
                for k, v in item.items():
                    kl = k.lower()
                    if keyword not in kl or "rate" in kl or "net" in kl:
                        continue
                    fv = _finite(v)
                    if fv is not None:
                        total += fv
                return total

            result = {}
            if isinstance(data, list) and data:
                main_net = 0.0
                dde_net = 0.0
                inflow_sum = 0.0
                outflow_sum = 0.0
                latest_date = None
                latest_main = 0.0
                latest_dde = 0.0
                latest_inflow = 0.0
                latest_outflow = 0.0
                for item in data:
                    if isinstance(item, dict):
                        main = _finite(item.get("main_net_inflow")) or 0
                        dde = _finite(item.get("dde_net")) or 0
                        inflow = _gather(item, "inflow")
                        outflow = _gather(item, "outflow")
                        main_net += main
                        dde_net += dde
                        inflow_sum += inflow
                        outflow_sum += outflow
                        d = item.get("date")
                        if d is not None and (latest_date is None or str(d) > str(latest_date)):
                            latest_date = d
                            latest_main = main
                            latest_dde = dde
                            latest_inflow = inflow
                            latest_outflow = outflow
                result = {
                    "main_net_inflow": main_net,
                    "dde_net": dde_net,
                    "inflow": inflow_sum,
                    "outflow": outflow_sum,
                    "main_net_inflow_latest": latest_main,
                    "dde_net_latest": latest_dde,
                    "inflow_latest": latest_inflow,
                    "outflow_latest": latest_outflow,
                    "date": latest_date,
                }
            self._set_cached("flow", code, str(days), result)
            self._mark_ok()
            return result or None
        except Exception:
            self._mark_fail()
            return None


# ============ 指标计算 ============
# 指标计算窗口（缩短可大幅减少 zb.get 耗时，不影响最新日指标值）
# ma60 需 60 个交易日，90 自然日窗口足够；rsi 为递归算法需更充足预热。
IND_START = "20260520"      # 90 自然日（ma/kdj/macd/boll/obv）
IND_RSI_START = "20260601"  # 60 自然日（rsi6/12/24）


# 技术指标最新值快照缓存（code:end_date -> dict，跨重启复用）
IND_CACHE_TABLE = "指标缓存"

_IND_FIELDS = (
    "ma5", "ma10", "ma20", "ma60", "k", "d", "j",
    "rsi6", "rsi12", "rsi24", "dif", "dea", "macd",
    "boll_upper", "boll_mid", "boll_lower", "obv",
)


def compute_indicators(rows_by_code: Dict[str, List[dict]],
                       start: str = IND_START, end: str = END) -> Dict[str, Dict[str, Any]]:
    """
    对每只股票计算技术指标，返回 {code: {ma5..ma60, rsi6/12/24, k/d/j, dif/dea/macd,
    boll_upper/mid/lower, obv}}。

    加速策略：
    1. zb.get 支持一次合并多个指标（ma,kdj,macd,boll,obv,rsi），
       避免 8 次全量读库（73s -> 30s）。
    2. 结果按 (code, end) 缓存到 ./mydb，同日重复扫描直接读缓存。
    """
    codes = list(rows_by_code.keys())
    if not codes:
        return {}
    cached = _read_indicator_cache(codes, end)
    if cached:
        return cached
    result = _compute_indicators_uncached(codes, start, end)
    if result:
        _write_indicator_cache(result, end)
    return result


def _compute_indicators_uncached(codes: List[str], start: str,
                                 end: str) -> Dict[str, Dict[str, Any]]:
    """真实计算（首次）：一次合并 ma/kdj/macd/boll/obv/rsi6，另算 rsi12/24。"""
    try:
        merged = zb.get(
            "ma,kdj,macd,boll,obv,rsi", codes,
            start=start, end=end, frequency="1d",
            n=["5,10,20,60", None, None, "20,2", None, "6"],
        )
        rsi12 = zb.get("rsi", codes, start=IND_RSI_START, end=end, frequency="1d", n="12")
        rsi24 = zb.get("rsi", codes, start=IND_RSI_START, end=end, frequency="1d", n="24")
    except Exception:
        return {}

    # 取最后一根的值
    def last(series, field, default=None):
        if not series:
            return default
        try:
            v = series[-1].get(field)
        except (IndexError, TypeError, AttributeError):
            return default
        fv = _finite(v)
        return fv if fv is not None else default

    result = {}
    for code in codes:
        m_rows = (merged or {}).get(code) or []
        result[code] = {
            "ma5": last(m_rows, "ma5"),
            "ma10": last(m_rows, "ma10"),
            "ma20": last(m_rows, "ma20"),
            "ma60": last(m_rows, "ma60"),
            "k": last(m_rows, "k"),
            "d": last(m_rows, "d"),
            "j": last(m_rows, "j"),
            "rsi6": last(m_rows, "rsi"),
            "rsi12": last(rsi12.get(code) or [], "rsi"),
            "rsi24": last(rsi24.get(code) or [], "rsi"),
            "dif": last(m_rows, "dif"),
            "dea": last(m_rows, "dea"),
            "macd": last(m_rows, "macd"),
            "boll_upper": last(m_rows, "upper"),
            "boll_mid": last(m_rows, "mid"),
            "boll_lower": last(m_rows, "lower"),
            "obv": last(m_rows, "obv"),
        }
    return result


def _read_indicator_cache(codes: List[str], end: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """读 ./mydb 指标缓存；end 一致且有数据时返回 {code: ind}，否则 None。"""
    try:
        cached: Dict[str, Dict[str, Any]] = {}
        for prefix in ("0", "3", "6", "9"):
            rows = rd.vals(IND_CACHE_TABLE, prefix + "*", end).do()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("code", ""))
                if code in cached:
                    continue
                cached[code] = {f: row.get(f) for f in _IND_FIELDS}
        return cached or None
    except Exception:
        return None


def _write_indicator_cache(result: Dict[str, Dict[str, Any]], end: str) -> None:
    """把指标快照批量写入 ./mydb（pipe.mset）。"""
    try:
        pipe = rd.pipe()
        for code, ind in result.items():
            value = dict(ind)
            value["code"] = code
            value["date"] = end
            pipe.mset(IND_CACHE_TABLE, code, end, value)
        pipe.do()
    except Exception:
        pass


SCORE_TABLE = "因子快照"          # code:end -> {score, factor_scores, details, ...}
SCORE_INDEX_TABLE = "因子索引"    # score_key:end -> {code, name, score}（按综合分范围过滤）


def _score_key(score) -> str:
    """综合分转定宽字符串：字符串序 == 数值序（000.00~100.00）。

    范围表达式按字典序比较，直接写 "88.5" 会与 "9.5" 顺序错乱，
    必须补零定宽使字典序与数值序一致。
    """
    s = _finite(score)
    s = max(0.0, min(100.0, s)) if s is not None else 0.0
    return f"{s:07.2f}"


def save_factor_snapshot(items: List[dict], end: str) -> None:
    """把评分快照批量写入 ./mydb（pipe.mset）。

    同一 pipe 双表写入：
    - "因子快照": (code, end) 全量数据，按 code 精确读、复用评分
    - "因子索引": (score_key, end) 轻量索引，支持按综合分范围直接过滤
    同 end 交易日重复扫描覆盖写入（幂等）。
    """
    if not items:
        return
    try:
        pipe = rd.pipe()
        now = time.time()
        for item in items:
            code = item.get("code")
            if not code:
                continue
            # 完整条目快照（含 passed/warnings/full 等全部展示字段），
            # 快速过滤命中后无需重算即可完整还原展示
            snapshot = dict(item)
            snapshot["date"] = end
            snapshot["ts"] = now          # 快照时间戳，供 factor_freshness 时效判定
            pipe.mset(SCORE_TABLE, code, end, snapshot)
            pipe.mset(SCORE_INDEX_TABLE, _score_key(item.get("score")), end, {
                "code": code,
                "name": item.get("name") or "",
                "score": item.get("score"),
            })
        pipe.do()
    except Exception:
        pass


def load_factor_snapshot(codes: List[str], end: str) -> Dict[str, dict]:
    """pipe.mget 批量读取因子快照。返回 {code: dict}，供二次扫描直接复用评分。

    注意：单条 mget 时底层 do() 返回 dict（非 list），统一包一层。
    """
    if not codes:
        return {}
    try:
        pipe = rd.pipe()
        for code in codes:
            pipe.mget(SCORE_TABLE, code, end)
        rows = pipe.do()
        if isinstance(rows, dict):
            rows = [rows]
        return {c: r for c, r in zip(codes, rows) if isinstance(r, dict)}
    except Exception:
        return {}


def query_factor_scores(lo: float, hi: float, end: str = END,
                        desc: bool = False, limit: Optional[int] = None) -> List[dict]:
    """按综合分区间直接过滤（服务端范围查询，无需全量拉取）。

    - lo/hi：0~100 综合分闭区间
    - desc=False：按分升序；desc=True：高分在前
    - 返回 [{code, name, score}, ...]
    """
    try:
        op = "<" if desc else ">"
        query = f"{_score_key(lo)}{op}{_score_key(hi)}"
        rows = rd.vals(SCORE_INDEX_TABLE, query, str(end)).do()
        if isinstance(rows, dict):
            rows = [rows]
        rows = [r for r in rows if isinstance(r, dict)]
        rows.sort(key=lambda r: -(_finite(r.get("score")) or 0))
        if limit:
            rows = rows[:limit]
        return rows
    except Exception:
        return []


def filter_by_filters(filters: Optional[Dict[str, Any]], item: dict) -> bool:
    """重放 FilterPanel 过滤条件，判定快照条目是否命中。

    与 ScanWorker 的 _passes_market/_indicator/_online 判定逻辑等价，
    但数据源改为快照中已落库的 details/full 字段（避免重复计算与在线调用）。
    在线/实时因子的快照值是否可信，由 factor_freshness 另行提示。
    """
    f = filters or {}
    details = item.get("details") or {}
    full = item.get("full") or {}
    code = item.get("code") or ""
    name = str(item.get("name") or "")

    def _sf(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    close = _sf(details.get("close"))
    if close is None or close <= 0:
        return False

    # 市场板块（代码前缀）
    boards = f.get("boards", {})
    if boards and any(boards.values()):
        matched = (
            (code.startswith(("60", "00")) and boards.get("main")) or
            (code.startswith("30") and boards.get("gem")) or
            (code.startswith("68") and boards.get("star")) or
            (code.startswith("920") and boards.get("bse"))
        )
        if not matched:
            return False

    # 非ST
    if f.get("non_st") and "ST" in name.upper():
        return False

    # 股价
    price_min, price_max = f.get("price_min"), f.get("price_max")
    if price_min is not None and close < price_min:
        return False
    if price_max is not None and close > price_max:
        return False

    # 成交额（界面单位为亿）
    amount = _sf(details.get("amount"))
    amount_min, amount_max = f.get("amount_min"), f.get("amount_max")
    if amount_min is not None and (amount is None or amount < amount_min * 1e8):
        return False
    if amount_max is not None and (amount is None or amount > amount_max * 1e8):
        return False

    # 换手率
    turnover = _sf(details.get("turnover"))
    turnover_min, turnover_max = f.get("turnover_min"), f.get("turnover_max")
    if turnover_min is not None and (turnover is None or turnover < turnover_min):
        return False
    if turnover_max is not None and (turnover is None or turnover > turnover_max):
        return False

    # 涨幅
    pct = _sf(details.get("pct_chg"))
    pct_min, pct_max = f.get("pct_chg_min"), f.get("pct_chg_max")
    if pct_min is not None and (pct is None or pct < pct_min):
        return False
    if pct_max is not None and (pct is None or pct > pct_max):
        return False

    # ---- 技术面（均线/突破/涨停/RSI/量比）----
    ma20, ma60 = _sf(details.get("ma20")), _sf(details.get("ma60"))
    macd, rsi6 = _sf(details.get("macd")), _sf(details.get("rsi6"))
    if f.get("close_above_ma20") and (close is None or ma20 is None or close <= ma20):
        return False
    if f.get("ma20_above_ma60") and (ma20 is None or ma60 is None or ma20 <= ma60):
        return False
    if f.get("close_above_ma60") and (close is None or ma60 is None or close <= ma60):
        return False
    if f.get("macd_positive") and (macd is None or macd <= 0):
        return False
    if f.get("break_high20") and not details.get("is_break"):
        return False  # 快照用已算好的 is_break，与扫描口径一致
    if f.get("limit_up_recent") and (_finite(details.get("limit_up_5")) or 0) <= 0:
        return False
    rsi_min, rsi_max = f.get("rsi_min"), f.get("rsi_max")
    if rsi_min is not None and (rsi6 is None or rsi6 < rsi_min):
        return False
    if rsi_max is not None and (rsi6 is None or rsi6 > rsi_max):
        return False
    vol_ratio = _sf(details.get("vol_ratio"))
    vr_min, vr_max = f.get("vol_ratio_min"), f.get("vol_ratio_max")
    if vr_min is not None and (vol_ratio is None or vol_ratio < vr_min):
        return False
    if vr_max is not None and (vol_ratio is None or vol_ratio > vr_max):
        return False

    # ---- 在线类（财务/估值/资金流）——用快照值重放 ----
    rev = _sf(details.get("rev_yoy"))
    profit = _sf(details.get("profit_yoy"))
    if f.get("revenue_yoy_positive") and rev is not None and rev <= 0:
        return False
    if f.get("profit_yoy_positive") and profit is not None and profit <= 0:
        return False
    cash = _sf(full.get("ocf"))
    if f.get("cash_flow_positive") and cash is not None and cash <= 0:
        return False
    main_net = _sf(full.get("main_net_latest")) or _sf(details.get("main_net"))
    if f.get("main_flow_positive") and main_net is not None and main_net <= 0:
        return False

    # 市值：优先接口精确市值（元->亿），旧快照回退 total_mv_yi（5日均值近似）
    market_cap = _sf(full.get("market_cap"))
    if market_cap is not None:
        market_cap = market_cap / 1e8
    else:
        market_cap = _sf(full.get("total_mv_yi"))
    mc_min, mc_max = f.get("market_cap_min"), f.get("market_cap_max")
    if mc_min is not None and (market_cap is None or market_cap < mc_min):
        return False
    if mc_max is not None and (market_cap is None or market_cap > mc_max):
        return False

    # PE/PB/ROE
    pe = _sf(details.get("pe")) or _sf(full.get("pe_ttm"))
    pb = _sf(details.get("pb")) or _sf(full.get("pb"))
    roe = _sf(full.get("roe"))
    for vmin, vmax, value in (
        (f.get("pe_min"), f.get("pe_max"), pe),
        (f.get("pb_min"), f.get("pb_max"), pb),
        (f.get("roe_min"), f.get("roe_max"), roe),
    ):
        if vmin is not None and (value is None or value < vmin):
            return False
        if vmax is not None and (value is None or value > vmax):
            return False

    # 负债率上限 / 股息率下限
    debt_max = f.get("debt_max")
    if debt_max is not None:
        debt = _sf(full.get("debt_to_assets"))
        if debt is None or debt > debt_max:
            return False
    dy_min = f.get("dividend_yield_min")
    if dy_min is not None:
        dy = _sf(full.get("dividend_yield"))
        if dy is None or dy < dy_min:
            return False

    # ---- 行业/概念（快照已存，无需再查 bk）----
    sw1 = str(full.get("sw1") or "")
    sw2 = str(full.get("sw2") or "")
    sw3 = str(full.get("sw3") or "")
    sw = str(full.get("sw_industry") or "")
    l3, l2, l1 = f.get("industry_l3"), f.get("industry_l2"), f.get("industry_l1")
    if l3 and l3 != "全部":
        # 新版快照有 sw3 精确匹配；旧快照回退子串近似
        if sw3 and l3 != sw3:
            return False
        if not sw3 and l3 not in sw and sw not in l3:
            return False
    elif l2 and l2 != "全部":
        if sw2 and l2 != sw2:
            return False
        if not sw2 and l2 != sw:
            return False
    elif l1 and l1 != "全部":
        if sw1 and l1 != sw1:
            return False
        if not sw1 and l1 not in sw and sw not in l1:
            return False
    concept = f.get("concept")
    if concept and concept != "全部":
        concepts = full.get("concepts")
        lst = concepts if isinstance(concepts, list) else str(concepts or "").split(",")
        if concept not in [str(x).strip() for x in lst]:
            return False

    return True


def filter_factor_table(filters: Optional[Dict[str, Any]], codes: Optional[List[str]] = None,
                        end: str = END, min_score: Optional[float] = None,
                        limit: Optional[int] = None) -> List[dict]:
    """组合过滤：pipe.mget 批量读因子快照（宽表）-> 逐条重放条件。

    - codes 为空则从因子索引表取该 end 下全部已落库 code
    - 返回按综合分降序的完整条目 [{code, name, score, details, full, ...}]
    """
    if not codes:
        try:
            query = f"{_score_key(0.0)}>{_score_key(100.0)}"
            rows = rd.vals(SCORE_INDEX_TABLE, query, str(end)).do()
            if isinstance(rows, dict):
                rows = [rows]
            codes = [r.get("code") for r in rows if isinstance(r, dict) and r.get("code")]
        except Exception:
            codes = []
    if not codes:
        return []
    snap = load_factor_snapshot(codes, end)
    results: List[dict] = []
    for code in codes:
        item = snap.get(code)
        if not isinstance(item, dict):
            continue
        if min_score is not None:
            s = _finite(item.get("score"))
            if s is None or s < min_score:
                continue
        if filters and not filter_by_filters(filters, item):
            continue
        results.append(item)
        if limit and len(results) >= limit:
            break
    results.sort(key=lambda r: -(_finite(r.get("score")) or 0))
    return results


def factor_freshness(item: dict) -> dict:
    """按数据来源判断快照中各因子是否新鲜（数据/缓存替换策略）。

    返回 {ts, age_hours, has_stale, has_realtime, factors:{factor: 状态}}：
    - fresh   本地历史因子，end 不变即稳定
    - stale   在线接口因子，距快照时间超 ONLINE_TTL_HOURS，接口数据需替换后重扫
    - realtime 盘中实时因子，快照为代理值，盘中需重算
    """
    from factors import (FACTOR_SOURCES, SRC_ONLINE, SRC_REALTIME,
                         ONLINE_TTL_HOURS)
    ts = _finite(item.get("ts"))
    now = time.time()
    age_h = (now - ts) / 3600.0 if ts is not None else float("inf")
    status: Dict[str, str] = {}
    for fkey, src in FACTOR_SOURCES.items():
        if src == SRC_ONLINE:
            status[fkey] = "stale" if age_h > ONLINE_TTL_HOURS else "fresh"
        elif src == SRC_REALTIME:
            status[fkey] = "realtime"
        else:
            status[fkey] = "fresh"
    return {
        "ts": ts,
        "age_hours": round(age_h, 1) if ts is not None else None,
        "has_stale": any(v == "stale" for v in status.values()),
        "has_realtime": any(v == "realtime" for v in status.values()),
        "factors": status,
    }


# ============ 板块环境 ============
def compute_board_env(rows_by_code: Dict[str, List[dict]],
                      board_info: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, float]:
    """
    计算每只股票所属板块的环境分。
    返回 {code: board_score}，基于板块内股票平均涨幅。

    ``board_info`` 为 ``load_stock_boards`` 的结果（code -> sw1 等），
    传入后不再重复调用 ``bk.get``，大幅减少板块库查询次数。
    """
    # 每只股票最新涨幅
    code_pct = {}
    for code, rows in rows_by_code.items():
        valid = valid_trading_rows(rows)
        if valid:
            code_pct[code] = _finite(valid[-1].get("pct_chg")) or 0

    # 板块 -> 股票映射（申万一级）
    board_stocks = defaultdict(list)
    code_boards: Dict[str, List[str]] = {}
    if board_info:
        for code, info in board_info.items():
            sw1 = (info or {}).get("sw1") or ""
            if sw1:
                code_boards[code] = [sw1]
                board_stocks[sw1].append(code)
    else:
        # 回退：逐只查询申万一级
        for code in code_pct:
            try:
                boards = bk.get(code, 1, "name")
                if isinstance(boards, list):
                    code_boards[code] = [b for b in boards]
                    for b in boards:
                        board_stocks[b].append(code)
            except Exception:
                continue

    # 板块平均涨幅
    board_avg = {}
    for board, codes in board_stocks.items():
        pcts = [code_pct[c] for c in codes if c in code_pct]
        if pcts:
            board_avg[board] = sum(pcts) / len(pcts)

    # 每只股票取其所属板块的最大平均涨幅作为环境分
    code_board_score = {}
    for code in code_pct:
        best = 0.0
        for b in code_boards.get(code, []):
            best = max(best, board_avg.get(b, 0.0))
        code_board_score[code] = best
    return code_board_score


# ============ 行业 / 概念板块（三级联动） ============
INDUSTRY_TREE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "industry_tree.json")


def load_industry_tree() -> Optional[Dict[str, Any]]:
    """读取本地行业树缓存。"""
    try:
        if not os.path.exists(INDUSTRY_TREE_FILE):
            return None
        with open(INDUSTRY_TREE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("l1"):
            return data
    except Exception:
        pass
    return None


def save_industry_tree(tree: Dict[str, Any]) -> None:
    """保存行业树缓存到本地文件。"""
    try:
        with open(INDUSTRY_TREE_FILE, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False)
    except Exception:
        pass


def build_industry_tree(rows_by_code: Dict[str, List[dict]],
                        sample_limit: int = 2000) -> Dict[str, Any]:
    """遍历股票，构建 一级->二级->三级 行业联动树 + 概念板块数据。

    每只股票一次调用 ``bk.get(code, None, "name,category")`` 即可拿到
    概念 / 申万一级 / 申万二级 / 申万三级全部分类。

    返回结构::

        {
            "l1": ["电子", ...],                     # 全部一级行业
            "l2": {"电子": ["半导体", ...], ...},      # 一级 -> 二级
            "l3": {"半导体": ["半导体材料", ...], ...}, # 二级 -> 三级
            "concepts": ["芯片概念", ...],            # 全部概念板块（去重排序）
            "industry": {"002371": {"l1": "电子", "l2": "半导体", "l3": "半导体设备"}, ...},
            "concept_of": {"002371": ["芯片概念", ...], ...},
        }
    """
    l1_set: Set[str] = set()
    l2_map: Dict[str, Set[str]] = defaultdict(set)
    l3_map: Dict[str, Set[str]] = defaultdict(set)
    concept_set: Set[str] = set()
    industry_of: Dict[str, Dict[str, str]] = {}
    concept_of: Dict[str, List[str]] = {}

    count = 0
    for code in rows_by_code:
        if count >= sample_limit:
            break
        try:
            boards = bk.get(code, None, "name,category")
            if not isinstance(boards, list):
                count += 1
                continue
            c_l1 = c_l2 = c_l3 = ""
            c_concepts: List[str] = []
            for item in boards:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                name = str(item[0]).strip()
                cat = str(item[1]).strip()
                if not name:
                    continue
                if cat == "概念":
                    c_concepts.append(name)
                    concept_set.add(name)
                elif cat == "申万一级":
                    c_l1 = name
                    l1_set.add(name)
                elif cat == "申万二级":
                    c_l2 = name
                elif cat == "申万三级":
                    c_l3 = name
            if c_l1 and c_l2:
                l2_map[c_l1].add(c_l2)
            if c_l2 and c_l3:
                l3_map[c_l2].add(c_l3)
            industry_of[code] = {"l1": c_l1, "l2": c_l2, "l3": c_l3}
            concept_of[code] = c_concepts
        except Exception:
            pass
        count += 1

    return {
        "l1": sorted(l1_set),
        "l2": {k: sorted(v) for k, v in l2_map.items()},
        "l3": {k: sorted(v) for k, v in l3_map.items()},
        "concepts": sorted(concept_set),
        "industry": industry_of,
        "concept_of": concept_of,
    }


def compute_market_env(rows_by_code: Dict[str, List[dict]]) -> float:
    """基于等权指数估算大盘强弱，返回 0-10 分"""
    try:
        # 用 zb.zhishu 等权指数
        idx = zb.get("zhishu", original=rows_by_code, method=1, base=1000)
        if isinstance(idx, list) and len(idx) >= 2:
            last = idx[-1].get("close")
            prev = idx[-2].get("close")
            if last and prev and prev > 0:
                chg = (last / prev - 1) * 100
                # 涨幅 > 3% 强，< -3% 弱
                return max(0, min(10, 5 + chg * 1.5))
    except Exception:
        pass
    return 5.0


# ============ 扫描结果扩展字段 ============
def guess_board(code: str) -> str:
    """根据代码推断上市板块。"""
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301", "302")):
        return "创业板"
    if code.startswith(("920", "8", "4")):
        return "北交所"
    if code.startswith("6"):
        return "沪主板"
    if code.startswith("0"):
        return "深主板"
    return "-"


def aggregate_recent(valid: List[dict], n: int = 5) -> Dict[str, Any]:
    """查询日近 n 个交易日的聚合值。

    收盘价/换手/振幅/市值取均值，成交量/成交额取累计。
    返回的键与用户列表对应：
    avg_close_5d / vol_5d / amount_5d / turnover_5d / amplitude_5d /
    total_mv_5d / float_mv_5d
    """
    window = valid[-n:] if len(valid) >= n else valid
    if not window:
        return {}
    avg = lambda key: _mean(_finite(r.get(key)) for r in window)
    total = lambda key: _sum(_finite(r.get(key)) for r in window)
    return {
        "avg_close_5d": avg("close"),
        "vol_5d": total("volume"),
        "amount_5d": total("amount"),
        "turnover_5d": avg("turnover"),
        "amplitude_5d": avg("amplitude"),
        "total_mv_5d": avg("total_mv"),
        "float_mv_5d": avg("float_mv"),
    }


def _mean(seq):
    vals = [v for v in seq if v is not None]
    return sum(vals) / len(vals) if vals else None


def _sum(seq):
    vals = [v for v in seq if v is not None]
    return sum(vals) if vals else None


def judge_yaogu(valid: List[dict], ind: Optional[Dict[str, Any]] = None) -> str:
    """判断"妖股气质"标签。

    规则（基于查询日近5日与最新单日）：
    - 近5日累计涨幅 >=25% +2，>=15% +1
    - 最新日涨幅 >=8% +2，>=5% +1
    - 近5日平均换手 >=10% +1
    - 近5日平均振幅 >=6% +1
    - 5日均线相对20日均线乖离 >=10% +1
    总分 >=5 -> 强妖股气质；>=3 -> 妖股气质；否则空。
    """
    if not valid:
        return ""
    try:
        if len(valid) < 6:
            return ""
        c_now = _finite(valid[-1].get("close"))
        c_pre5 = _finite(valid[-6].get("close"))
        if not c_now or not c_pre5:
            return ""
        chg5 = (c_now / c_pre5 - 1) * 100
        last_pct = _finite(valid[-1].get("pct_chg")) or 0
        win5 = valid[-5:]
        avg_turnover = _mean([_finite(r.get("turnover")) for r in win5]) or 0
        avg_amplitude = _mean([_finite(r.get("amplitude")) for r in win5]) or 0

        score = 0
        if chg5 >= 25:
            score += 2
        elif chg5 >= 15:
            score += 1
        if last_pct >= 8:
            score += 2
        elif last_pct >= 5:
            score += 1
        if avg_turnover >= 10:
            score += 1
        if avg_amplitude >= 6:
            score += 1
        if ind:
            ma5 = _finite(ind.get("ma5"))
            ma20 = _finite(ind.get("ma20"))
            if ma5 and ma20 and ma20 > 0 and (ma5 / ma20 - 1) * 100 >= 10:
                score += 1
        if score >= 5:
            return "强妖股气质"
        if score >= 3:
            return "妖股气质"
        return ""
    except Exception:
        return ""


def load_stock_boards(codes: List[str],
                      max_concepts: int = 8) -> Dict[str, Dict[str, str]]:
    """批量查询每只股票的申万行业 + 概念板块。

    bk.get 支持一次传入整个 codes 列表（底层板块索引在内存），
    远快于逐只查询。返回 {code: {"sw1":.., "sw2":.., "sw3":.., "concepts": "a/b/c"}}，
    概念取前 ``max_concepts`` 个，超过用"等"省略。
    """
    result: Dict[str, Dict[str, str]] = {
        str(code): {"sw1": "", "sw2": "", "sw3": "", "concepts": ""}
        for code in codes
    }
    if not codes:
        return result
    try:
        boards_map = bk.get(codes, None, "name,category")
    except Exception:
        return result
    if not isinstance(boards_map, dict):
        return result
    for code, boards in boards_map.items():
        info = result.get(str(code))
        if info is None or not isinstance(info, dict):
            continue
        if not isinstance(boards, list):
            continue
        concepts: List[str] = []
        for item in boards:
            if not isinstance(item, list) or len(item) < 2:
                continue
            name = str(item[0]).strip()
            cat = str(item[1]).strip()
            if cat == "概念":
                concepts.append(name)
            elif cat == "申万一级":
                info["sw1"] = name
            elif cat == "申万二级":
                info["sw2"] = name
            elif cat == "申万三级":
                info["sw3"] = name
        if concepts:
            shown = concepts[:max_concepts]
            extra = "等" if len(concepts) > max_concepts else ""
            info["concepts"] = "/".join(shown) + extra
    return result
