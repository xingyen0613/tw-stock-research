#!/usr/bin/env python3
"""維護 AIHOT 精選的本地完整副本。

AIHOT 的 items API 只吃 window=24h|7d（30d 直接回 400），但 /selected/snapshot
不受時間窗限制。所以先 bootstrap 一份完整副本，之後只收 changes 增量，
就能在本地做任意時間範圍的檢索。

用法：
    python3 aihot_sync.py              # 沒有副本就 bootstrap，有就收增量
    python3 aihot_sync.py --rebuild    # 強制重建
"""
import argparse, json, time, urllib.parse, urllib.request
from pathlib import Path

BASE = "https://aihot.virxact.com/api/v1"
UA = "aihot-skill/1.5.4 (+https://aihot.virxact.com/aihot-skill/)"
CACHE = Path(__file__).resolve().parents[4] / ".cache" / "aihot" / "selected.json"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def bootstrap():
    """分頁抓完整快照。cursor 是同步水位（逐頁恆定），nextPage 只用於翻頁，兩者不可混用。"""
    items, page, cursor = [], None, None
    t0 = time.time()
    while True:
        url = f"{BASE}/selected/snapshot?fields=default&limit=1000"
        if page:
            url += f"&page={urllib.parse.quote(page)}"
        r = get(url)
        if cursor is None:
            cursor = r.get("cursor")          # 只認第一頁的水位
        items += r.get("items", [])
        if not r.get("hasMore"):
            break
        page = r.get("nextPage")
    print(f"bootstrap：{len(items)} 筆，{time.time() - t0:.1f}s")
    return {"cursor": cursor, "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": items}


def incremental(state):
    """用同步水位收增量。整頁套用成功才存新 cursor。"""
    by_id = {i["id"]: i for i in state["items"]}
    cursor, applied = state["cursor"], 0
    while True:
        r = get(f"{BASE}/selected/changes?cursor={urllib.parse.quote(cursor)}&limit=100")
        for c in r.get("changes", []):
            if c.get("op") == "upsert":
                by_id[c["item"]["id"]] = c["item"]
            elif c.get("op") == "remove":
                by_id.pop(c.get("id") or c.get("item", {}).get("id"), None)
            applied += 1
        cursor = r.get("cursor", cursor)
        if not r.get("hasMore"):
            break
    state.update(cursor=cursor, items=list(by_id.values()),
                 synced_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    print(f"增量：套用 {applied} 筆變更，現有 {len(state['items'])} 筆")
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if a.rebuild or not CACHE.exists():
        state = bootstrap()
    else:
        state = incremental(json.loads(CACHE.read_text(encoding="utf-8")))

    CACHE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    size = CACHE.stat().st_size / 1024 / 1024
    print(f"副本：{CACHE}（{len(state['items'])} 筆，{size:.2f} MB）")


if __name__ == "__main__":
    main()
