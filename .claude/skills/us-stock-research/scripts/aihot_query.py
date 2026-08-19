#!/usr/bin/env python3
"""從 AIHOT 本地副本撈出某標的的消息面事件，套時間權重後輸出 events.json。

與 aihot skill 預設用法的三點差異（依報告需求調整）：
1. 只取消息面 category（industry / ai-products / ai-models），排除 paper / tip
2. 排序用自算的 weight，不用 AIHOT 的 score（實測 p50=72、p90=79，區分度太低）
3. 不受 24h/7d 限制 —— 查的是本地副本

用法：
    python3 aihot_query.py NVDA --out events.json
    python3 aihot_query.py AVGO --keywords "Broadcom,博通" --days 180
"""
import argparse, json, math, re, sys, datetime
from pathlib import Path

CACHE = Path(__file__).resolve().parents[4] / ".cache" / "aihot" / "selected.json"
NEWS_CATEGORIES = {"industry", "ai-products", "ai-models"}
HALF_LIFE_DAYS = 45          # 照實測的時間密度定：31–90d 佔 1538 筆是主體
LOW_HIT_THRESHOLD = 5        # 低於此值就該在報告裡註明 AIHOT 覆蓋不足

# 只放覆蓋密度足夠、值得預設的標的；其餘一律用 --keywords 指定
TICKER_KEYWORDS = {
    "NVDA": ["NVIDIA", "英伟达", "英偉達", "黄仁勋", "黃仁勳", "Jensen Huang"],
    "GOOGL": ["Google", "谷歌", "Gemini", "DeepMind"], "GOOG": ["Google", "谷歌", "Gemini", "DeepMind"],
    "MSFT": ["Microsoft", "微软", "微軟", "Copilot"],
    "META": ["Meta", "扎克伯格", "Llama"],
    "AMZN": ["Amazon", "亚马逊", "亞馬遜", "AWS"],
    "AAPL": ["Apple", "苹果", "蘋果"],
    "TSLA": ["Tesla", "特斯拉", "马斯克", "馬斯克", "xAI"],
    "AMD": ["AMD"], "AVGO": ["Broadcom", "博通"], "TSM": ["TSMC", "台积电", "台積電"],
    "ORCL": ["Oracle", "甲骨文"], "CRWV": ["CoreWeave"], "PLTR": ["Palantir"],
}


def timeline_date(item):
    """AIHOT 的時間軸口徑：慢推信源用收錄時間，歷史回填歸位到原發布日。"""
    pub, disc = item.get("publishedAt"), item.get("discoveredAt")
    if not pub:
        return disc
    if not disc:
        return pub
    try:
        d = (datetime.datetime.fromisoformat(disc.replace("Z", "+00:00"))
             - datetime.datetime.fromisoformat(pub.replace("Z", "+00:00")))
        return pub if d.total_seconds() > 72 * 3600 else disc
    except ValueError:
        return disc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--keywords", help="逗號分隔，覆寫內建對照表")
    ap.add_argument("--days", type=int, default=365, help="往回幾天（本地副本不受 API 的 7d 限制）")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--out", help="輸出 events.json 路徑")
    a = ap.parse_args()

    if not CACHE.exists():
        sys.exit(f"[ERR] 找不到本地副本 {CACHE}，先跑 aihot_sync.py")

    kws = ([k.strip() for k in a.keywords.split(",") if k.strip()] if a.keywords
           else TICKER_KEYWORDS.get(a.ticker.upper()))
    if not kws:
        sys.exit(f"[ERR] {a.ticker} 沒有內建關鍵詞，請用 --keywords 指定")

    state = json.loads(CACHE.read_text(encoding="utf-8"))
    now = datetime.datetime.now(datetime.timezone.utc)
    patterns = [(k, re.compile(re.escape(k), re.I)) for k in kws]
    events, skipped_category = [], 0

    for it in state["items"]:
        if it.get("category") not in NEWS_CATEGORIES:
            skipped_category += 1
            continue
        blob = " ".join(filter(None, [it.get("title"), it.get("summary"), it.get("originalTitle")]))
        matched = [k for k, p in patterns if p.search(blob)]
        if not matched:
            continue

        tl = timeline_date(it)
        try:
            days = (now - datetime.datetime.fromisoformat(tl.replace("Z", "+00:00"))).days
        except (ValueError, AttributeError):
            continue
        if days > a.days or days < 0:
            continue

        events.append({
            "title": it["title"],
            "date": tl[:10],
            "days_ago": days,
            "category": it.get("category"),
            "source": it.get("source", {}).get("name"),
            "summary": it.get("summary"),
            "tier": "L3",                     # 一律先標 L3，回溯到 SEC 才升級
            "aihot_url": it.get("links", {}).get("aihot"),
            "original_url": it.get("links", {}).get("original"),
            "matched_keywords": matched,
            "weight": round(len(matched) * math.exp(-days / HALF_LIFE_DAYS), 4),
        })

    events.sort(key=lambda e: e["weight"], reverse=True)
    events = events[:a.top]

    result = {
        "ticker": a.ticker.upper(), "keywords": kws,
        "synced_at": state.get("synced_at"), "pool_size": len(state["items"]),
        "window_days": a.days, "half_life_days": HALF_LIFE_DAYS,
        "total_hits": len(events), "low_coverage": len(events) < LOW_HIT_THRESHOLD,
        "events": events,
    }

    if a.out:
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{a.ticker.upper()}：命中 {len(events)} 則消息面事件"
          f"（關鍵詞 {'/'.join(kws)}，回看 {a.days} 天，副本 {len(state['items'])} 筆）")
    if result["low_coverage"]:
        print(f"[WARN] 命中數 < {LOW_HIT_THRESHOLD}，AIHOT 對此標的覆蓋不足 —— "
              f"報告應跳過 AI 生態章節並註明，不要硬湊")
    for e in events[:10]:
        print(f"  {e['weight']:.3f}  {e['date']}  [{e['category']}]  {e['title'][:56]}")
    if a.out:
        print(f"\n輸出：{a.out}")


if __name__ == "__main__":
    main()
