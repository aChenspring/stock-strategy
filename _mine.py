# -*- coding: utf-8 -*-
"""临时参数挖掘：网格搜索用户场景（6000元）下 annual/total 收益率最优组合。"""
import time

from backtest import run_backtest

BASE = dict(
    strategy="factor_default", start="", end="", fee_rate=0.0005,
    init_cash=6000, stop_loss=-12.0, take_profit=20.0,
    rebalance_every=2, universe="all", max_codes=300, pre_days=60,
    market_filter=True, market_filter_mode="strong", ma_up_days=3,
    config=None, top_n=10, hold_days=15, min_score=55.0, max_buy_pct=6.0,
)


def run(tag, diff):
    cfg = dict(BASE)
    cfg.update(diff)
    t0 = time.time()
    try:
        m = run_backtest(cfg, progress_cb=lambda msg, p: None)["metrics"]
    except Exception as e:  # noqa: BLE001
        print(f"[{tag}] FAIL: {e}", flush=True)
        return None
    dt = time.time() - t0
    print(f"[{tag}] total={m['total_return']:7.2f}% annual={m['annual_return']:7.2f}% "
          f"mdd={m['max_drawdown']:6.2f}% trades={m['trade_count']:4d} "
          f"win={m['win_rate']:5.1f} pf={m['profit_factor']:5.2f} ({dt:.0f}s)", flush=True)
    return m


def sweep_dim(name, values, others=None):
    print(f"\n===== 维度 {name} =====", flush=True)
    best, best_v = None, None
    for v in values:
        d = dict(others or {})
        d[name] = v
        m = run(f"{name}={v}", d)
        if m and (best is None or m["annual_return"] > best["annual_return"]):
            best, best_v = m, v
    return best_v, best


if __name__ == "__main__":
    # 1) 单维度粗搜（固定其余为基准）
    dims = [
        ("min_score", [45, 50, 55, 60, 65, 70]),
        ("hold_days", [5, 10, 15, 20, 25, 30]),
        ("rebalance_every", [1, 2, 3]),
        ("stop_loss", [-6, -8, -10, -12, -15, -18]),
        ("take_profit", [10, 15, 20, 25, 30]),
        ("max_buy_pct", [3, 4, 6, 8, 10]),
        ("top_n", [5, 10, 15, 20, 30]),
        ("market_filter_mode", ["strong", "above", "off"]),
        ("ma_up_days", [2, 3, 4]),
    ]
    for name, values in dims:
        sweep_dim(name, values)
