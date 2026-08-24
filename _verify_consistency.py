# -*- coding: utf-8 -*-
"""端到端一致性验证：扫描口径(6m窗口) vs 回测口径(更长预热) 的指标与判定。

两端共用 IndicatorSeries + judge_at，理论上必然一致；本脚本实证确认
数据窗口差异不会导致指标/判定漂移。
"""
from collections import Counter

from backtest import IndicatorSeries, judge_at
from screen_common import DEFAULT_SCAN_FILTERS, score_factor_local
from strategy_data import (A_SHARE_PREFIXES, END, calc_window_start, load_market_rows)
from strategy_schema import build_factor_defs, build_rules_map

fdefs = build_factor_defs(None)
rmap = build_rules_map(None)


def _default_start(end: str, back_days: int) -> str:
    from datetime import datetime, timedelta
    dt = datetime.strptime(end, "%Y%m%d")
    return (dt - timedelta(days=back_days * 1.6)).strftime("%Y%m%d")


def main():
    scan_start = calc_window_start(END, "6m")
    bt_start = _default_start(END, 180)
    print(f"scan window: {scan_start}~{END}   bt window: {bt_start}~{END}")

    # 抽一批真实股票（混合板块）
    all_rows = load_market_rows(A_SHARE_PREFIXES, scan_start, END)
    sample = sorted(all_rows)[::max(1, len(all_rows) // 60)]
    print(f"样本 {len(sample)} 只")

    rows_scan = load_market_rows(A_SHARE_PREFIXES, scan_start, END)
    rows_bt = load_market_rows(A_SHARE_PREFIXES, bt_start, END)

    ind_diff = 0
    judge_diff = 0
    both_hit = 0
    checked = 0
    for code in sample:
        r_scan = rows_scan.get(code)
        r_bt = rows_bt.get(code)
        if not r_scan or not r_bt:
            continue
        s_scan = IndicatorSeries(code, r_scan)
        s_bt = IndicatorSeries(code, r_bt)
        date = s_bt.dates[-1]
        if not s_scan.has_date(date):
            continue
        checked += 1
        ind_s = s_scan.indicator_at(date)
        ind_b = s_bt.indicator_at(date)
        for k in ("ma5", "ma10", "ma20", "ma60", "macd", "rsi6", "k", "d", "vol_ratio"):
            if ind_s.get(k) != ind_b.get(k):
                ind_diff += 1
                if ind_diff <= 10:
                    print(f"  IND DIFF {code} {k}: scan={ind_s.get(k)} bt={ind_b.get(k)}")
        r_s = judge_at(s_scan, date, DEFAULT_SCAN_FILTERS, True, 6.0, 55.0,
                       fdefs, rmap, True, "factor_default")
        r_b = judge_at(s_bt, date, DEFAULT_SCAN_FILTERS, True, 6.0, 55.0,
                       fdefs, rmap, True, "factor_default")
        if (r_s is not None) != (r_b is not None):
            judge_diff += 1
            print(f"  JUDGE DIFF {code} {date}: scan={'HIT' if r_s else 'miss'} bt={'HIT' if r_b else 'miss'}")
        if r_s is not None and r_b is not None:
            both_hit += 1
            if r_s["scored"]["total"] != r_b["scored"]["total"]:
                print(f"  SCORE DIFF {code}: scan={r_s['scored']['total']} bt={r_b['scored']['total']}")
    print(f"检查 {checked} 只；指标不一致 {ind_diff} 处；判定不一致 {judge_diff} 只；双命中 {both_hit} 只")


if __name__ == "__main__":
    main()
