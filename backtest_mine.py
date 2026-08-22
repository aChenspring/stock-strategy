# -*- coding: utf-8 -*-
"""全策略挖掘（第 5 阶段·对照）：验证 100 万大资金场景下，
低频参数（hold15/maxbuy6/topn20）是否同样优于原定稿（hold10/topn25/maxbuy8）。
用法：python backtest_mine.py
"""
import time

from backtest import run_backtest

CASES = [
    ("100万_hold10_topn25_maxbuy8(旧定稿)", dict(
        init_cash=1_000_000, top_n=25, hold_days=10, max_buy_pct=8.0)),
    ("100万_hold15_topn20_maxbuy6(低频)", dict(
        init_cash=1_000_000, top_n=20, hold_days=15, max_buy_pct=6.0)),
    ("6000_hold15_topn10_maxbuy6(新定稿)", dict(
        init_cash=6000, top_n=10, hold_days=15, max_buy_pct=6.0)),
]


def main():
    for i, (tag, diff) in enumerate(CASES, 1):
        cfg = dict(
            strategy="factor_default", start="", end="",
            fee_rate=0.0005, min_score=55.0, stop_loss=-12.0,
            take_profit=20.0, rebalance_every=2, universe="all",
            max_codes=400, pre_days=60, market_filter=True,
            market_filter_mode="strong", ma_up_days=3, config=None,
        )
        cfg.update(diff)
        t0 = time.time()
        print(f"[{i}/{len(CASES)}] {tag} ...", flush=True)
        try:
            m = run_backtest(cfg, progress_cb=lambda msg, p: None)["metrics"]
        except Exception as e:  # noqa: BLE001
            print(f"    FAIL: {e}")
            continue
        dt = time.time() - t0
        print(f"    收益 {m['total_return']:>7.2f}%  回撤 {m['max_drawdown']:>6.2f}%  "
              f"夏普 {m['sharpe']:>4.2f}  盈亏比 {m['profit_factor']:>5.2f}  "
              f"交易 {m['trade_count']:>4d}  ({dt:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
