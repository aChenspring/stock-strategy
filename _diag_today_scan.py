# -*- coding: utf-8 -*-
"""当天实时扫描 0 命中诊断：复现 ScanWorker 判定链。
输出：行情/候选池规模、大盘等权指数状态(RSI14/chg20/chg60)与 market_ok、
当天候选综合分分布 top、judge_at 命中数（与界面扫描同源）。"""
import time
import random
from collections import Counter

from strategy_data import (load_market_rows, valid_trading_rows,
                           START as START, END as END, calc_window_start)
from strategy_schema import build_factor_defs, build_rules_map
from backtest import DEFAULT_BT_CONFIG, scan_market_ok, IndicatorSeries, judge_at
from screen_common import (DEFAULT_SCAN_FILTERS, passes_market_filters,
                           score_factor_local)
from strategies import get_strategies

PREFIXES = ["0*", "3*", "6*", "920*"]
t0 = time.time()
scan_end = END
scan_window = "6m"
scan_start = calc_window_start(scan_end, scan_window)
print(f"[{time.time()-t0:6.1f}s] 加载行情 {scan_start}~{scan_end} ...", flush=True)
rows_by_code = load_market_rows(PREFIXES, scan_start, scan_end)
print(f"[{time.time()-t0:6.1f}s] 行情加载完成，共{len(rows_by_code)}只", flush=True)

market_pool: dict = {}
candidates: dict = {}
for code, rows in rows_by_code.items():
    valid = valid_trading_rows(rows)
    if len(valid) < 60:
        continue
    market_pool[code] = valid
    if passes_market_filters(code, valid, DEFAULT_SCAN_FILTERS):
        candidates[code] = valid
print(f"[{time.time()-t0:6.1f}s] market_pool={len(market_pool)} 行情过滤后候选池={len(candidates)}", flush=True)

# ---- 大盘等权指数状态（与 scan_market_ok 同口径）----
by_date: dict = {}
for rows in market_pool.values():
    for r in rows:
        dt = r.get("date")
        c = r.get("close")
        if dt and c is not None:
            by_date.setdefault(dt, []).append(c)
dates = sorted(by_date)
closes: list = []
last = None
for d in dates:
    cs = by_date[d]
    v = sum(cs) / len(cs) if cs else last
    last = v
    closes.append(v)


def _rsi(vals, n=14):
    if len(vals) <= n:
        return None
    gains = losses = 0.0
    for i in range(len(vals) - n, len(vals)):
        diff = vals[i] - vals[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


mc = closes[-1]
chg20 = (mc / closes[-21] - 1.0) * 100.0 if len(closes) >= 21 else None
chg60 = (mc / closes[-61] - 1.0) * 100.0 if len(closes) >= 61 else None
r14 = _rsi(closes)
print(f"[{time.time()-t0:6.1f}s] 大盘等权指数 末日={dates[-1]} 收盘={mc:.2f} "
      f"RSI14={r14:.1f} chg20={chg20:.2f}% chg60={chg60:.2f}%", flush=True)

bt_cfg = DEFAULT_BT_CONFIG
print(f"[{time.time()-t0:6.1f}s] market_filter={bt_cfg.get('market_filter')} mode={bt_cfg.get('market_filter_mode')} "
      f"rsi<{bt_cfg.get('market_rsi_threshold')} chg20<{bt_cfg.get('market_chg20_max')} "
      f"chg20b<{bt_cfg.get('market_chg20_max2')} chg60>{bt_cfg.get('market_chg60_min')}", flush=True)
market_ok = scan_market_ok(
    market_pool,
    mode=bt_cfg.get("market_filter_mode", "oversold"),
    ma_days=20,
    up_days=bt_cfg.get("ma_up_days", 3),
    rsi_threshold=bt_cfg.get("market_rsi_threshold", 40.0),
    chg20_max=bt_cfg.get("market_chg20_max"),
    chg20_max2=bt_cfg.get("market_chg20_max2"),
    chg60_min=bt_cfg.get("market_chg60_min"))
print(f"[{time.time()-t0:6.1f}s] market_ok={market_ok}  "
      f"({'放行买入' if market_ok else '非入场窗口 → 全部不推荐'})", flush=True)

# ---- 判定日与综合分分布（候选池全量本地评分，毫秒级）----
last_date_raw = Counter(r[-1]["date"] for r in candidates.values()).most_common(1)[0][0]
last_date = str(last_date_raw)  # IndicatorSeries.idx_by_date 的 key 为 str
_sample_date = next(iter(candidates.values()))[-1]["date"]
print(f"[{time.time()-t0:6.1f}s] 判定日 raw={last_date_raw!r}({type(last_date_raw).__name__}) "
      f"→ str={last_date}；行内 date 样本 {_sample_date!r}({type(_sample_date).__name__})", flush=True)
fdefs = build_factor_defs(None)
rmap = build_rules_map(None)
min_score = next((s.get("min_score") for s in get_strategies()
                  if s["key"] == "factor_default"), None) or 0.0
max_buy_pct = DEFAULT_BT_CONFIG.get("max_buy_pct")
print(f"[{time.time()-t0:6.1f}s] 判定日={last_date} min_score={min_score} max_buy_pct={max_buy_pct}", flush=True)

scores = []
n_scored = 0
first_err = None
passed_real = 0
passed_force = 0  # market_ok=True 模拟放行（验证类型bug修复后分数/过滤是否可达）
for code, rows in candidates.items():
    s = IndicatorSeries(code, rows)
    if not s.has_date(last_date):
        continue
    i = s.index_at(last_date)
    recent = s.rows[max(0, i - 4):i + 1]
    ind = s.indicator_at(last_date)
    if not ind:
        continue
    n_scored += 1
    try:
        scored = score_factor_local(fdefs, recent, ind, rmap)
    except Exception as e:  # noqa: BLE001
        if first_err is None:
            first_err = f"{code}: {e!r}"
        continue
    total = scored["total"]
    scores.append(total)
    r_real = judge_at(s, last_date, DEFAULT_SCAN_FILTERS, market_ok, max_buy_pct,
                      min_score, fdefs, rmap, True, "factor_default")
    r_force = judge_at(s, last_date, DEFAULT_SCAN_FILTERS, True, max_buy_pct,
                       min_score, fdefs, rmap, True, "factor_default")
    if r_real is not None:
        passed_real += 1
    if r_force is not None:
        passed_force += 1

if first_err:
    print(f"[{time.time()-t0:6.1f}s] 评分首异常: {first_err}", flush=True)
scores.sort(reverse=True)


def pct(v, p):
    if not v:
        return None
    v = sorted(v)
    k = max(0, min(len(v) - 1, int(round(len(v) * p))))
    return v[k]


print(f"[{time.time()-t0:6.1f}s] 当日有数据可评分={n_scored} "
      f"综合分 max={scores[0]:.1f} p90={pct(scores, .9):.1f} p75={pct(scores, .75):.1f} "
      f"p50={pct(scores, .5):.1f}", flush=True)
print(f"[{time.time()-t0:6.1f}s] 综合分>=48 的票数 = {sum(1 for x in scores if x >= 48)}", flush=True)
print(f"[{time.time()-t0:6.1f}s] top20 综合分: {[round(x, 1) for x in scores[:20]]}", flush=True)
print(f"[{time.time()-t0:6.1f}s] judge_at 命中(真实 market_ok={market_ok}) = {passed_real}", flush=True)
print(f"[{time.time()-t0:6.1f}s] judge_at 命中(market_ok 强制放行) = {passed_force}  ← 类型bug修复后可达命中", flush=True)
print(f"[{time.time()-t0:6.1f}s] 耗时 {time.time()-t0:.1f}s", flush=True)
