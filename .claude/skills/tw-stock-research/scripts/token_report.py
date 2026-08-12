#!/usr/bin/env python3
"""統計本次報告產製的 token 消耗，按主對話與各 subagent 拆分。

用法：
    python3 scripts/token_report.py                    # 自動抓最近活動的 session
    python3 scripts/token_report.py --session <id>     # 指定 session
    python3 scripts/token_report.py --tools            # 額外列出工具回傳體積明細

「成本當量」欄位把四種 token 折算成同一單位再算百分比，因為 cache_read 的單價
只有 input 的 1/10、output 是 5 倍，直接加總會嚴重高估 cache_read 的比重。
折算係數 = Anthropic 官方定價比例，與具體模型單價無關。
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Claude Code 把專案路徑的非英數字元換成 "-" 當作 projects 底下的目錄名
PROJECT_DIR = (Path.home() / ".claude/projects" /
               re.sub(r"[^A-Za-z0-9]", "-", str(Path.cwd().resolve())))

# 相對 input token 的單價倍率（Anthropic 定價比例，跨模型一致）
W_INPUT, W_CACHE_WRITE, W_CACHE_READ, W_OUTPUT = 1.0, 1.25, 0.1, 5.0


def scan(path):
    """讀一個 jsonl，回傳 token 統計與工具回傳體積。"""
    acc = dict(inp=0, cw=0, cr=0, out=0, turns=0, ws=0, wf=0)
    tool_chars = defaultdict(int)
    tool_calls = defaultdict(int)
    names = {}
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        if "usage" in msg:
            u = msg["usage"]
            acc["turns"] += 1
            acc["inp"] += u.get("input_tokens", 0)
            acc["cw"] += u.get("cache_creation_input_tokens", 0)
            acc["cr"] += u.get("cache_read_input_tokens", 0)
            acc["out"] += u.get("output_tokens", 0)
            srv = u.get("server_tool_use", {})
            acc["ws"] += srv.get("web_search_requests", 0)
            acc["wf"] += srv.get("web_fetch_requests", 0)
        for blk in msg.get("content") or []:
            if not isinstance(blk, dict):
                continue
            kind = blk.get("type")
            if kind == "tool_use":
                names[blk.get("id")] = blk.get("name")
                tool_calls[blk.get("name")] += 1
            elif kind == "server_tool_use":
                nm = "SRV:" + str(blk.get("name"))
                names[blk.get("id")] = nm
                tool_calls[nm] += 1
            elif kind in ("tool_result", "web_search_tool_result", "web_fetch_tool_result"):
                nm = names.get(blk.get("tool_use_id"), kind)
                tool_chars[nm] += len(json.dumps(blk.get("content"), ensure_ascii=False))
    return acc, tool_chars, tool_calls


def equiv(a):
    """成本當量：折算成 input token 單位。"""
    return a["inp"] * W_INPUT + a["cw"] * W_CACHE_WRITE + a["cr"] * W_CACHE_READ + a["out"] * W_OUTPUT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="session id（預設取最近活動的）")
    ap.add_argument("--tools", action="store_true", help="列出工具回傳體積明細")
    args = ap.parse_args()

    if args.session:
        main_log = PROJECT_DIR / f"{args.session}.jsonl"
    else:
        logs = sorted(PROJECT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not logs:
            sys.exit(f"找不到 session log：{PROJECT_DIR}")
        main_log = logs[-1]
    if not main_log.exists():
        sys.exit(f"找不到 {main_log}")

    sid = main_log.stem
    rows = []

    acc, mt_chars, mt_calls = scan(main_log)
    rows.append(("主對話（orchestration）", "主模型", acc, mt_chars, mt_calls))

    sub_dir = PROJECT_DIR / sid / "subagents"
    for log in sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.is_dir() else []:
        meta_path = log.with_suffix("").with_suffix(".meta.json")
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        a, tc, calls = scan(log)
        rows.append((meta.get("description", log.stem), meta.get("model", "?"), a, tc, calls))

    total_eq = sum(equiv(r[2]) for r in rows) or 1

    print(f"\n{'='*96}\nToken 使用報告 · session {sid[:8]}\n{'='*96}")
    hdr = f"{'階段 / Agent':<30}{'模型':<9}{'cache寫':>11}{'cache讀':>12}{'output':>9}{'當量':>12}{'佔比':>7}"
    print(hdr)
    print("-" * 96)
    for desc, model, a, _, _ in rows:
        eq = equiv(a)
        label = desc if len(desc) <= 28 else desc[:27] + "…"
        print(f"{label:<30}{model:<9}{a['cw']:>11,}{a['cr']:>12,}{a['out']:>9,}"
              f"{eq:>12,.0f}{eq/total_eq*100:>6.1f}%")
    print("-" * 96)
    t = {k: sum(r[2][k] for r in rows) for k in ("inp", "cw", "cr", "out", "turns", "ws", "wf")}
    print(f"{'合計':<30}{'':<9}{t['cw']:>11,}{t['cr']:>12,}{t['out']:>9,}{total_eq:>12,.0f}{100.0:>6.1f}%")
    print(f"\n原始 token：input {t['inp']:,} ｜ cache 寫入 {t['cw']:,} ｜ cache 讀取 {t['cr']:,} ｜ output {t['out']:,}")
    print(f"總 turn 數 {t['turns']} ｜ WebSearch {t['ws']} 次 ｜ WebFetch {t['wf']} 次")
    print("「當量」= 折算成 input token 單價的成本比重（cache寫×1.25、cache讀×0.1、output×5），"
          "百分比依此計算。")

    if args.tools:
        print(f"\n{'='*96}\n工具回傳體積（chars，約 ÷2.5 為中文 token）\n{'='*96}")
        for desc, _, _, tc, calls in rows:
            if not tc:
                continue
            sub = sum(tc.values())
            print(f"\n▸ {desc}  合計 {sub:,} chars ≈ {int(sub/2.5):,} tok")
            for name, chars in sorted(tc.items(), key=lambda x: -x[1])[:6]:
                print(f"    {chars:>10,} ({chars/sub*100:5.1f}%)  {name} ×{calls.get(name, 0)}")


if __name__ == "__main__":
    main()
