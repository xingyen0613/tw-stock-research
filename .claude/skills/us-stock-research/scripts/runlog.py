#!/usr/bin/env python3
"""記錄每次產報告卡在哪，並跨次聚合出常見問題。

台股與美股 skill 共用同一支 runs.jsonl，這樣「常見問題」才看得到全貌。

用法：
    # 產完報告後記一筆（issues 是 JSON 陣列）
    python3 runlog.py add --skill us-stock-research --ticker NVDA \
        --issues '[{"phase":"B-3","type":"source_missing","detail":"找不到法說會逐字稿","action":"降級標 L3"}]' \
        --tokens 420000 --duration 18

    # 隔一段時間回來看常見問題
    python3 runlog.py summary
    python3 runlog.py summary --since 2026-08-01
"""
import argparse, json, collections, datetime, sys
from pathlib import Path

LOG = Path(__file__).resolve().parents[4] / "runlog" / "runs.jsonl"
ISSUE_TYPES = {"source_missing", "api_not_entitled", "parse_failed",
               "rate_limited", "data_conflict", "token_spike", "other"}


def cmd_add(a):
    try:
        issues = json.loads(a.issues) if a.issues else []
    except json.JSONDecodeError as e:
        sys.exit(f"[ERR] --issues 不是合法 JSON：{e}")

    for i in issues:
        if i.get("type") not in ISSUE_TYPES:
            sys.exit(f"[ERR] issue.type 必須是 {sorted(ISSUE_TYPES)}，收到 {i.get('type')!r}")
        if not i.get("phase"):
            sys.exit("[ERR] 每筆 issue 都要有 phase")

    rec = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "skill": a.skill, "ticker": a.ticker.upper(), "issues": issues,
           "tokens": a.tokens, "duration_min": a.duration, "ok": not issues}
    if a.note:
        rec["note"] = a.note

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"已記錄 {a.ticker.upper()}（{len(issues)} 筆 issue）→ {LOG}")


def cmd_summary(a):
    if not LOG.exists():
        sys.exit(f"還沒有任何紀錄（{LOG}）")

    runs = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.since:
        runs = [r for r in runs if r["ts"][:10] >= a.since]
    if not runs:
        sys.exit("篩選後沒有紀錄")

    by_type = collections.Counter()
    by_phase = collections.Counter()
    detail = collections.defaultdict(list)
    for r in runs:
        for i in r["issues"]:
            by_type[i["type"]] += 1
            by_phase[i["phase"]] += 1
            detail[i["type"]].append(f"{r['ticker']}: {i.get('detail', '')[:60]}")

    clean = sum(1 for r in runs if r["ok"])
    toks = [r["tokens"] for r in runs if r.get("tokens")]
    print(f"共 {len(runs)} 次報告，{clean} 次無 issue（{clean / len(runs) * 100:.0f}%）")
    if toks:
        print(f"token：平均 {sum(toks) // len(toks):,}／最高 {max(toks):,}")

    print("\n問題類型 Top：")
    for t, n in by_type.most_common():
        print(f"  {n:3}  {t}")
        if a.verbose:
            for d in detail[t][:3]:
                print(f"         └ {d}")

    print("\n卡關 Phase Top：")
    for p, n in by_phase.most_common():
        print(f"  {n:3}  {p}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add")
    p.add_argument("--skill", required=True)
    p.add_argument("--ticker", required=True)
    p.add_argument("--issues", help='JSON 陣列，每筆需含 phase/type/detail/action')
    p.add_argument("--tokens", type=int)
    p.add_argument("--duration", type=float, help="分鐘")
    p.add_argument("--note")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("summary")
    p.add_argument("--since", help="YYYY-MM-DD")
    p.add_argument("--verbose", action="store_true", help="附每類問題的實例")
    p.set_defaults(func=cmd_summary)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
