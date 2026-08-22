# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
p = r"C:\Users\wxb\Downloads\free-stockdb-windows-v0.3.1-more-power\stockdb\调用方式\python\AI策略python开发接口文档.md"
lines = open(p, encoding="utf-8").read().splitlines()
out = []
keys = ("get_last_tick", "get_ticks", "get_price")
for i, ln in enumerate(lines):
    if any(k in ln for k in keys):
        out.append(f"--- line {i+1} ---")
        for j in range(i, min(len(lines), i + 45)):
            out.append(f"{j+1}: {lines[j]}")
        out.append("")
open("_doc_out.txt", "w", encoding="utf-8").write("\n".join(out))
print("written lines:", len(out))
