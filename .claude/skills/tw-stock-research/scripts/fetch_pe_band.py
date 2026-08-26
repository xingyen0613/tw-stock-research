#!/usr/bin/env python3
"""算本益比河流圖（PE band）的資料，落成 pe_band.json。

用法：
    # 台股：自己去 FinMind 抓
    python3 scripts/fetch_pe_band.py 2308 --years 5 --out output/xxx/pe_band.json

    # 美股或其他市場：資料先用別的管道取好落成 JSON 再餵進來
    python3 scripts/fetch_pe_band.py --from-json raw.json --out pe_band.json
    # raw.json 格式：
    # {"meta":{"ticker":"NVDA","name":"NVIDIA","currency":"USD"},
    #  "prices":[{"date":"2026-08-25","close":180.5}, ...],
    #  "eps":[{"period":"FY2027Q1","eps":0.81,"effective_from":"2026-05-28"}, ...]}
    # effective_from = 該季財報「實際公布日」，不是季末日。PE 從那天起才換成新的 TTM。

台股的 TTM EPS 切換日直接用證交所每日本益比（FinMind TaiwanStockPER）反推，
不用法定申報期限猜——實測台達電 2026Q2 是 07-29 換、嘉澤是 08-14 換，差 16 天。

輸出的 price 是**月均價**（該月所有交易日收盤價平均），不是日收盤：
TTM EPS 本來就是每季才動一次的階梯，日線精度不會多給任何資訊，
而月線讓單檔 HTML 少掉 20 倍的內嵌數字。
"""

import argparse
import calendar
import json
import math
import os
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

BASE = "https://api.finmindtrade.com/api/v4/data"

# 本益比區間的色階：dataviz skill 的 blue ramp，ordinal 用法（淺→深＝低倍→高倍）。
# 這 5 階是「白底 + ordinal」驗證器唯一過關的組合（相鄰 ΔL≥0.06、最淺階對白底 2.11:1）。
# 驗證指令見 references/report-structure.md。**band 數上限 5 就是這條色階的長度決定的**，
# 不要自己補第 6 個顏色——要更多層就把級距調大。
PE_RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
MAX_BANDS = len(PE_RAMP)
STEP_CANDIDATES = (5, 10, 15, 20, 25, 50)   # 使用者指定 5 倍為基本單位，不夠才往上跳
MIN_COVERAGE = 0.80                          # 有效 PE 月份低於這個比例就不畫


def fetch(dataset, stock_id, start):
    params = {"dataset": dataset, "data_id": stock_id, "start_date": start}
    req = urllib.request.Request(f"{BASE}?{urllib.parse.urlencode(params)}")
    token = os.environ.get("FINMIND_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=90) as r:
        body = json.load(r)
    if body.get("status") != 200:
        sys.exit(f"[{dataset}] FinMind 回應失敗：{body.get('msg')}")
    return body.get("data", [])


def quantile(vals, p):
    s = sorted(vals)
    k = (len(s) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def load_tw(stock_id, years):
    """回傳 (月標籤, 月均價, 月底 TTM EPS, meta)。"""
    start_px = f"{2026 - years - 1}-01-01"          # 多抓一年墊 TTM
    price = fetch("TaiwanStockPrice", stock_id, start_px)
    per = fetch("TaiwanStockPER", stock_id, start_px)
    fs = fetch("TaiwanStockFinancialStatements", stock_id, f"{2026 - years - 2}-01-01")
    info = fetch("TaiwanStockInfo", stock_id, start_px)

    eps_q = sorted((r["date"], r["value"]) for r in fs if r["type"] == "EPS")
    # 每一季的 TTM = 該季與前三季的單季 EPS 相加
    ttm_by_q = {}
    for i in range(3, len(eps_q)):
        ttm_by_q[eps_q[i][0]] = round(sum(v for _, v in eps_q[i - 3:i + 1]), 4)

    close_by_date = {r["date"]: r["close"] for r in price}
    # 用當日「收盤價 ÷ 證交所本益比」反推市場當下採用的 TTM EPS，再對回財報的精確值
    implied = {}
    for r in per:
        c, p = close_by_date.get(r["date"]), r.get("PER")
        if c and p:
            implied[r["date"]] = c / p

    def match_quarter(x, after):
        """反推值對回哪一季的 TTM。證交所 PER 只有 2 位小數，容許 2% 誤差。
        限定季末日必須早於觀察日，避免誤配到還沒公布的下一季。"""
        best, err = None, None
        for qd, v in ttm_by_q.items():
            if v <= 0 or qd >= after:
                continue
            e = abs(v - x) / v
            if err is None or e < err:
                best, err = qd, e
        return best if err is not None and err < 0.02 else None

    def statutory(qd):
        """財報法定申報期限。只在 PER 反推不出切換日時當退路（虧損期間 PER 會是 0）。"""
        y, m = int(qd[:4]), int(qd[5:7])
        return {3: f"{y}-05-15", 6: f"{y}-08-14", 9: f"{y}-11-14", 12: f"{y + 1}-03-31"}[m]

    # 每季 TTM 的生效日：取反推結果第一次指向該季的那一天，就是市場實際換口徑的日子
    eff = {}
    for d in sorted(implied):
        qd = match_quarter(implied[d], d)
        if qd and qd not in eff:
            eff[qd] = d
    for qd in ttm_by_q:
        eff.setdefault(qd, statutory(qd))
    timeline = sorted((eff[qd], ttm_by_q[qd]) for qd in ttm_by_q)

    months = defaultdict(list)
    for r in price:
        months[r["date"][:7]].append((r["date"], r["close"]))

    labels, prices, ttms = [], [], []
    for m in sorted(months):
        days = sorted(months[m])
        labels.append(m)
        prices.append(round(statistics.mean(c for _, c in days), 2))
        # 該月最後一個交易日為準：那天為止已經生效的最後一組 TTM
        last_day = days[-1][0]
        cur = [v for d, v in timeline if d <= last_day]
        ttms.append(cur[-1] if cur else None)

    meta = {
        "stock_id": stock_id,
        "name": info[0].get("stock_name") if info else None,
        "currency": "TWD",
        "unit": "元",
        "pe_source": "證交所每日本益比（FinMind TaiwanStockPER）反推 TTM EPS 切換日，"
                     "TTM 數值取自財報單季 EPS 四季加總",
        "eps_quarters": len(eps_q),
    }
    return labels, prices, ttms, meta


def load_json(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    eps = sorted(raw["eps"], key=lambda r: r["effective_from"])
    months = defaultdict(list)
    for r in raw["prices"]:
        months[r["date"][:7]].append((r["date"], r["close"]))

    labels, prices, ttms = [], [], []
    for m in sorted(months):
        days = sorted(months[m])
        labels.append(m)
        prices.append(round(statistics.mean(c for _, c in days), 4))
        # 用當月最後一天判定，不是資料裡的最後一筆日期——月線 aggregate 的日期是
        # 月初（2026-08-01），拿它去比對財報公布日會把當月才公布的那一季整個漏掉。
        y, mo = int(m[:4]), int(m[5:7])
        month_end = f"{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"
        # 到該月底為止已經公布的最後 4 季，加總成 TTM
        pub = [r for r in eps if r["effective_from"] <= month_end]
        ttms.append(round(sum(r["eps"] for r in pub[-4:]), 4) if len(pub) >= 4 else None)

    meta = dict(raw.get("meta", {}))
    meta.setdefault("unit", meta.get("currency", ""))
    meta["pe_source"] = "TTM 為已公布四季 EPS 加總，切換日採各季財報實際公布日（effective_from）"
    return labels, prices, ttms, meta


def build(labels, prices, ttms, meta, years):
    # 只留最近 years 年，且 TTM 必須為正——EPS ≤ 0 時本益比沒有意義
    keep = len(labels) - years * 12
    if keep > 0:
        labels, prices, ttms = labels[keep:], prices[keep:], ttms[keep:]

    pe = [round(p / t, 2) if (t and t > 0) else None for p, t in zip(prices, ttms)]
    valid = [v for v in pe if v]
    coverage = len(valid) / len(pe) if pe else 0

    out = {
        "meta": {**meta, "months": len(labels), "years": years,
                 "coverage": round(coverage, 3), "ramp": PE_RAMP},
        "labels": labels, "price": prices, "ttm_eps": ttms, "pe": pe,
        "bands": [], "band_floor": [], "pe_stats": {}, "skip_reason": None,
    }

    if coverage < MIN_COVERAGE:
        out["skip_reason"] = (
            f"近 {years} 年只有 {len(valid)}/{len(pe)} 個月的近四季 EPS 為正"
            f"（覆蓋率 {coverage:.0%}，低於 {MIN_COVERAGE:.0%}），本益比河流圖無參考價值")
        return out

    p5, p95 = quantile(valid, 0.05), quantile(valid, 0.95)
    step = None
    for s in STEP_CANDIDATES:
        lo, hi = math.floor(p5 / s) * s, math.ceil(p95 / s) * s
        if round((hi - lo) / s) <= MAX_BANDS:
            step = s
            break
    if step is None:
        out["skip_reason"] = (
            f"近 {years} 年本益比區間 {min(valid):.1f}–{max(valid):.1f} 倍"
            f"（P5–P95 {p5:.1f}–{p95:.1f}），跨度過大無法用 {MAX_BANDS} 層區間表達，"
            "代表這段期間 EPS 波動遠大於股價，本益比河流圖無參考價值")
        return out

    lo, hi = math.floor(p5 / step) * step, math.ceil(p95 / step) * step
    edges = [lo + step * i for i in range(round((hi - lo) / step) + 1)]

    def line(mult):
        return [round(t * mult, 2) if (t and t > 0) else None for t in ttms]

    out["band_floor"] = line(edges[0])
    out["bands"] = [
        {"lo": edges[i], "hi": edges[i + 1], "color": PE_RAMP[i],
         "label": f"{edges[i]}–{edges[i + 1]} 倍", "upper": line(edges[i + 1])}
        for i in range(len(edges) - 1)
    ]
    out["meta"].update({"band_step": step, "band_lo": lo, "band_hi": hi,
                        "band_count": len(edges) - 1})
    out["pe_stats"] = {
        "last": valid[-1], "min": round(min(valid), 2), "max": round(max(valid), 2),
        "median": round(statistics.median(valid), 2),
        "p5": round(p5, 2), "p95": round(p95, 2),
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stock_id", nargs="?", help="台股代號（用 --from-json 時免填）")
    ap.add_argument("--from-json", help="非台股：已備好的 prices/eps JSON")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--out", default="pe_band.json")
    args = ap.parse_args()

    if args.from_json:
        labels, prices, ttms, meta = load_json(args.from_json)
    elif args.stock_id:
        labels, prices, ttms, meta = load_tw(args.stock_id, args.years)
    else:
        ap.error("要嘛給台股代號，要嘛給 --from-json")

    data = build(labels, prices, ttms, meta, args.years)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    m = data["meta"]
    print(f"✓ {m.get('stock_id') or m.get('ticker')} {m.get('name') or ''} → {args.out}")
    print(f"  {data['labels'][0]} ~ {data['labels'][-1]}（{m['months']} 個月）"
          f"｜有效 PE 覆蓋率 {m['coverage']:.0%}")
    if data["skip_reason"]:
        print(f"  ⚠ 不畫這張圖：{data['skip_reason']}")
    else:
        s = data["pe_stats"]
        print(f"  區間 {m['band_lo']}–{m['band_hi']} 倍，級距 {m['band_step']}，"
              f"{m['band_count']} 層")
        print(f"  PE 最新 {s['last']}｜中位 {s['median']}｜"
              f"最低 {s['min']}｜最高 {s['max']}")
        if m["band_step"] != 5:
            print(f"  註：本益比跨度超過 5 層 5 倍區間，級距自動放大為 {m['band_step']} 倍")


if __name__ == "__main__":
    main()
