# -*- coding: utf-8 -*-
"""
v9Limit5 连板启动预警 —— 聚宽(JoinQuant)平台移植版
=====================================================
将本地挖掘策略原样移植到聚宽，仅依赖量价+市值（与本地扫描/回测判定一致）。

策略逻辑（正样本 = 连续涨停≥5日事件的「启动前一日」）：
  1. 非 ST；
  2. 涨停基因：近20日涨停≥2 且 近60日涨停≥8 且 距上次涨停≤45交易日；
  3. 判定日当日未涨停（pct_chg < 8），避免追在已涨停日；
  4. 趋势：收盘站上MA20（偏离 0%~25%）且收盘不深破MA60（偏离 > -5%）；
  5. 流通市值 ≤ 100亿元（字段缺失不约束）。

涨停口径（pct = 收盘/昨收 - 1）：
  ST 5%(>=4.5) / 创业板·科创板 20%(>=19.5) / 北交所 30%(>=29.5) / 主板 10%(>=9.5)。

使用方式：
  A) 研究环境选股（推荐）：
     新建聚宽 Notebook -> 粘贴本文件全部内容 -> 修改 `TARGET_DATE` 为某个交易日 -> 运行。
     控制台输出该日所有满足条件的股票。
  B) 回测 / 模拟盘：
     聚宽「我的策略」新建策略 -> 粘贴本文件全部内容 -> 回测。
     （核心判定函数被回测部分复用，必须整文件粘贴；
      注意：回测前请删除文件末尾「if __name__ == '__main__':」那 3 行研究扫描代码，
      否则每次回测初始化会先全市场扫描一次（较慢）；
      回测每日全市场扫描较重，可自行把 run_daily 改为每 3 日扫描一次。）
"""
import pandas as pd
import numpy as np
from jqdata import get_price, get_all_securities, get_fundamentals, get_extras, query, valuation, indicator

# ================= 参数（与原策略一致） =================
MAX_FLOAT_MV = 1e10        # 流通市值上限：100亿元（单位：元）
MIN_BARS = 65              # 最少历史交易日（原策略 len(valid)>=65）
LIMIT20_MIN = 2            # 近20日涨停最少次数
LIMIT60_MIN = 8            # 近60日涨停最少次数
DAYS_SINCE_MAX = 45        # 距上次涨停最大间隔（交易日）
DEV20_MAX = 25.0           # 收盘/MA20 偏离上限（%）
DEV60_MIN = -5.0           # 收盘/MA60 偏离下限（%）
PCT_MAX = 8.0              # 判定日涨幅上限（%），>8 视为已涨停/大涨日

# 研究环境扫描截面日（改为你要扫描的交易日，收盘后跑）
TARGET_DATE = "2026-08-21"


# ================= 核心判定（与原 _check_limit5 逐条对齐） =================
def is_limit_up(code6, pct, is_st):
    """单日是否涨停（code6 为 6 位数字代码）。"""
    if is_st:
        return pct >= 4.5
    if code6.startswith(("30", "68")):          # 创业板 300/301，科创板 688/689
        return pct >= 19.5
    if code6.startswith(("92", "43", "83", "87")):  # 北交所 920 等
        return pct >= 29.5
    return pct >= 9.5


def check_limit5(code6, df, st_series=None, float_mv=None):
    """判定一个标的在 df 末行（判定日）是否满足 v9Limit5。

    参数：
      code6     : 6 位数字代码，如 "600000"
      df        : 日线 DataFrame，index=date(升序)，至少含 close/pre_close 两列
      st_series : 与 df 对齐的逐日 ST 标记 Series（默认 None -> 全部视为非 ST）
      float_mv  : 判定日流通市值（元），None 表示缺失不约束
    """
    df = df.dropna(subset=["close"]).sort_index()
    n = len(df)
    if n < MIN_BARS:
        return False
    if st_series is not None and bool(st_series.iloc[-1]):
        return False
    close = df["close"]
    # 复权(fq=pre)数据下 close.pct_change 即真实涨跌幅（等比缩放不影响比率）
    # 首行 NaN 时涨停判定为 False、涨幅阈值不排除，与原策略 `_finite(...) or 0.0` 一致
    pct = close.pct_change() * 100.0

    # 逐日 ST（历史 ST 状态影响涨停阈值）
    if st_series is not None:
        st_series = st_series.reindex(df.index).fillna(False).astype(bool)
        st_arr = st_series.values
    else:
        st_arr = np.zeros(n, dtype=bool)

    # 涨停基因统计（与原策略 for 循环一致）
    limit_flags = np.array([is_limit_up(code6, p, st_arr[i])
                            for i, p in enumerate(pct.values)])
    limit20 = int(limit_flags[-20:].sum())
    limit60 = int(limit_flags.sum())
    if limit20 < LIMIT20_MIN or limit60 < LIMIT60_MIN:
        return False
    days_since = -1
    for i in range(n - 1, -1, -1):
        if limit_flags[i]:
            days_since = (n - 1) - i
            break
    if days_since < 0 or days_since > DAYS_SINCE_MAX:
        return False

    # 判定日当日未涨停
    if pct.iloc[-1] >= PCT_MAX:
        return False

    # 趋势：MA20 / MA60
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    if pd.isna(ma20) or pd.isna(ma60) or ma20 <= 0 or ma60 <= 0:
        return False
    dev20 = (close.iloc[-1] / ma20 - 1) * 100.0
    dev60 = (close.iloc[-1] / ma60 - 1) * 100.0
    if not (0 < dev20 <= DEV20_MAX):
        return False
    if dev60 <= DEV60_MIN:
        return False

    # 市值约束（缺失不约束）
    if float_mv is not None and float_mv > MAX_FLOAT_MV:
        return False
    return True


# ================= 研究环境：全市场扫描 =================
def scan_market(date, verbose=True):
    """扫描 date 当日收盘后全市场，返回满足 v9Limit5 的股票代码列表(带 .后缀)。"""
    stocks = get_all_securities(types=["stock"], date=date)
    codes = list(stocks.index)
    code6_map = {c: c.split(".")[0] for c in codes}
    n_all = len(codes)

    # 1) 逐日 ST 状态（判定日 + 近70日历史，对齐原策略逐日 is_st）
    st_now, st_hist = {}, None
    try:
        st_df = get_extras("is_st", codes, start_date=date, end_date=date, df=True)
        if st_df is not None and len(st_df) and date in st_df.index:
            st_now = st_df.loc[date].fillna(False).astype(bool).to_dict()
        else:
            st_now = {c: False for c in codes}
    except Exception:
        st_now = {c: False for c in codes}
    try:
        st_hist = get_extras("is_st", codes, count=70, df=True)
    except Exception:
        st_hist = None

    # 2) 流通市值（元）
    mv_map = {}
    try:
        q = query(valuation.code, valuation.circulating_market_cap).filter(
            valuation.code.in_(codes))
        fund = get_fundamentals(q, date=date)
        mv_map = dict(zip(fund["code"], fund["circulating_market_cap"]))
    except Exception:
        pass

    # 3) 批量行情：近 70 个交易日（原策略需 >=65）
    px = get_price(codes, count=70, end_date=date, frequency="daily",
                   fields=["close", "pre_close"], skip_paused=True,
                   fq="pre", panel=False)
    hits = []
    done = 0
    for c in codes:
        if st_now.get(c):            # 非 ST 硬条件（与原策略一致）
            continue
        try:
            sub = px.xs(c, level=1)[["close", "pre_close"]]
        except Exception:
            continue
        if sub.empty:
            continue
        done += 1
        st_ser = None
        if st_hist is not None and c in st_hist.columns:
            st_ser = st_hist[c].reindex(sub.index).fillna(False).astype(bool)
        if check_limit5(code6_map[c], sub, st_ser, mv_map.get(c)):
            hits.append(c)
    if verbose:
        print(f"[{date}] 扫描 {n_all} 只（有效 {done}），命中 {len(hits)} 只：")
        for c in hits:
            name = stocks.loc[c, "display_name"] if "display_name" in stocks.columns else c
            mv = mv_map.get(c, float("nan"))
            print(f"  {c}  {name}  流通市值 {mv/1e8:.1f} 亿")
    return hits


def scan_market_loose(date, limit60_min=5, limit20_min=1, verbose=True):
    """放宽版（供观察市场临近候选）：把近60日涨停门槛降到 limit60_min。

    注意：这是诊断辅助函数，不是策略本身。
    """
    global LIMIT60_MIN, LIMIT20_MIN
    LIMIT60_MIN, LIMIT20_MIN = limit60_min, limit20_min
    try:
        return scan_market(date, verbose=verbose)
    finally:
        LIMIT60_MIN, LIMIT20_MIN = 8, 2


if __name__ == "__main__":
    hits = scan_market(TARGET_DATE, verbose=True)
    print("命中数:", len(hits))


# ================= 回测 / 模拟盘入口（粘贴以下到聚宽策略） =================
def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("order_volume_ratio", 0.25)
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003,
                             min_commission=5), type="stock")
    g.max_stocks = 10          # 最多同时持仓数
    g.hold_days = 10           # 最长持有交易日
    g.buy_days = {}            # code -> 买入日
    run_daily(scan_and_buy, time="09:40")


def scan_and_buy(context):
    """每交易日：用「前一交易日」收盘数据判定（避免使用当日未收盘行情），
    对候选按流通市值从小到大取前 max_stocks 只，可用现金等权买入。"""
    prev_date = get_trade_days(end_date=context.current_dt.date())[-2]
    stocks = get_all_securities(types=["stock"], date=prev_date)
    codes = [c for c in stocks.index if c.split(".")[0] not in ("",)]
    code6_map = {c: c.split(".")[0] for c in codes}
    n_all = len(codes)

    # 判定日 ST / 市值
    st_now, mv_map = {}, {}
    try:
        st_df = get_extras("is_st", codes, start_date=prev_date, end_date=prev_date, df=True)
        st_now = st_df.loc[prev_date].fillna(False).astype(bool).to_dict()
    except Exception:
        st_now = {c: False for c in codes}
    try:
        fund = get_fundamentals(
            query(valuation.code, valuation.circulating_market_cap)
            .filter(valuation.code.in_(codes)), date=prev_date)
        mv_map = dict(zip(fund["code"], fund["circulating_market_cap"]))
    except Exception:
        pass

    px = get_price(codes, count=70, end_date=prev_date, frequency="daily",
                   fields=["close", "pre_close"], skip_paused=True,
                   fq="pre", panel=False)
    cands = []
    for c in codes:
        if st_now.get(c):
            continue
        try:
            sub = px.xs(c, level=1)[["close", "pre_close"]]
        except Exception:
            continue
        if sub.empty:
            continue
        if check_limit5(code6_map[c], sub, None, mv_map.get(c)):
            cands.append(c)
    cands.sort(key=lambda c: (mv_map.get(c, 1e18), c))  # 小市值优先
    cands = cands[:g.max_stocks]
    log.info("[%s] 全市场 %d 只 -> 候选 %d 只 %s",
             prev_date, n_all, len(cands), cands)

    # ---- 卖出：超期 / 收盘跌破MA20 ----
    for c in list(context.portfolio.positions.keys()):
        if c not in context.portfolio.positions:
            continue
        if context.portfolio.positions[c].closeable_amount <= 0:
            continue
        hold = context.current_dt.date() - g.buy_days.get(c, context.current_dt.date())
        hist = attribute_history(c, 25, "1d", ["close"], skip_paused=True)
        ma20 = hist["close"].mean()
        if hold.days >= g.hold_days or (len(hist["close"]) and hist["close"].iloc[-1] < ma20):
            order_target(c, 0)

    # ---- 买入：可用现金等分 ----
    if cands:
        cash = context.portfolio.available_cash
        per = cash / len(cands)
        for c in cands:
            if context.portfolio.positions.get(c, None) is not None and \
                    context.portfolio.positions[c].total_amount > 0:
                continue
            order_value(c, per)
            g.buy_days[c] = context.current_dt.date()
