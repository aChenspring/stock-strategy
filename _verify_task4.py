# -*- coding: utf-8 -*-
"""任务4: 页面默认参数(6000/top10/min48/hold15) + oversold + 深度条件 全量回测
验证 +50% 目标或报告上限。
注：min_score 以当前页面默认 48 为准（strategies.py FACTOR_DEFAULT_MIN_SCORE
与 backtest.DEFAULT_BT_CONFIG 均已由 55 调整为 48；55 在 oversold 深度场景
不可达导致 0 交易，见 _verify_task4_out.txt 根因诊断）。
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from backtest import run_backtest

# ---- 使用页面默认参数（min_score=48，当前页面默认） ----
CASH = "6000"
TOP_N = "10"
HOLD = "15"
MIN_SCORE = "48"
STOP = "-12"
PROFIT = "20"
REBAL = "2"
MAX_BUY = "6"
MODE = "oversold"          # 市场过滤模式
CHG20 = "-14"
CHG20B = "-10"
CHG60 = "0"

cfg = {
    "init_cash": int(CASH),
    "top_n": int(TOP_N),
    "hold_days": int(HOLD),
    "min_score": int(MIN_SCORE),
    "stop_loss": int(STOP),
    "take_profit": int(PROFIT) if PROFIT.strip() else None,
    "rebalance_every": int(REBAL),
    "max_buy_pct": int(MAX_BUY),
    "market_filter_mode": MODE,
    "market_chg20_max": int(CHG20),
    "market_chg20_max2": int(CHG20B),
    "market_chg60_min": int(CHG60),
    "min_holding_pct": 0.0,
    "seed": 42,
    "max_codes": 0,          # 全量
    "start": "20200101",
    "date_end": None,
    "buy_times": [9.5],
    "save_trades": True,
}

t0 = time.time()
print(f"[T4] 页面默认(6000/top10/min48/hold15)+oversold+深度({CHG20}/{CHG20B}/{CHG60}) 全量回测 ...", flush=True)
res = run_backtest(cfg)
dt = time.time() - t0
m = res["metrics"]
print(f"[T4] total={m['total_return']:.2f}% annual={m['annual_return']:.2f}% "
      f"trades={m.get('n_trades', len(res.get('trades', [])))} "
      f"win={m.get('win_rate', float('nan')):.1f}% "
      f"pf={m.get('profit_factor', float('nan')):.2f} "
      f"md={m.get('max_drawdown', float('nan')):.1f}% elapsed={dt:.0f}s", flush=True)
days = sorted({t.get("buy_date", "")[:8] for t in res.get("trades", [])})
print(f"[T4] 买入日({len(days)}): {days}", flush=True)

with open("_verify_task4_out.txt", "w", encoding="utf-8") as f:
    f.write(f"total={m['total_return']:.2f}% annual={m['annual_return']:.2f}% "
            f"trades={m.get('n_trades', len(res.get('trades', [])))} "
            f"win={m.get('win_rate', float('nan')):.1f}% "
            f"pf={m.get('profit_factor', float('nan')):.2f} "
            f"md={m.get('max_drawdown', float('nan')):.1f}% elapsed={dt:.0f}s\n")
    f.write(f"buy_days={days}\n")
print("[T4] DONE", flush=True)
