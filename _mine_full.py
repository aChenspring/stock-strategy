# -*- coding: utf-8 -*-
"""临时：全市场池（max_codes=0）下扫描关键参数，找稳定高收益组合。"""
import time

from backtest import run_backtest

BASE = dict(
    strategy="factor_default", start="", end="", fee_rate=0.0005,
    init_cash=6000, stop_loss=-12.0, take_profit=20.0,
    rebalance_every=2, universe="all", max_codes=0, pre_days=60,
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
    for ms in (45, 50, 55, 60, 65, 70, 75):
        run(f"min_score={ms}", {"min_score": ms})
    for tn in (15, 20, 30):
        run(f"top_n={tn}", {"top_n": tn})
