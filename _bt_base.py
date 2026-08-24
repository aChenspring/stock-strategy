# -*- coding: utf-8 -*-
"""临时基准：统一口径后跑用户配置的回测，看收益率。"""
import json
import time

from backtest import run_backtest

cfg = dict(json.load(open(r"backtest_results/bt_20260822_211011.json",
                          encoding="utf-8"))["config"])
cfg.pop("config", None)
cfg["start"] = cfg.get("start") or ""
cfg["end"] = cfg.get("end") or ""

t0 = time.time()
res = run_backtest(cfg, progress_cb=lambda m, p: None)
print("elapsed:", round(time.time() - t0, 1))
m = res["metrics"]
print({k: m[k] for k in ("total_return", "annual_return", "max_drawdown",
                         "trade_count", "win_rate", "profit_factor")})
