# -*- coding: utf-8 -*-
"""临时：验证标的池规模 max_codes 对回测收益的影响（稳定性）。"""
import time

from backtest import run_backtest

BASE = dict(
    strategy="factor_default", start="", end="", fee_rate=0.0005,
    init_cash=6000, stop_loss=-12.0, take_profit=20.0,
    rebalance_every=2, universe="all", pre_days=60,
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
    print(f"[{tag}] total={m['total_return']:7.2f}% annual={m['annual_return']:7.2f}% "
          f"mdd={m['max_drawdown']:6.2f}% trades={m['trade_count']:4d} "
          f"win={m['win_rate']:5.1f} pf={m['profit_factor']:5.2f} ({time.time()-t0:.0f}s)", flush=True)
    return m


if __name__ == "__main__":
    for mc in (200, 300, 400, 600, 800, 1200, 2000, 0):
        run(f"max_codes={mc}", {"max_codes": mc})
