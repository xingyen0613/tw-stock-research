#!/usr/bin/env python3
"""從 FinMind API 抓台股逐季財務數據，算好比率，落成 financials.json。

用法：
    python3 scripts/fetch_financials.py 3533 --out /path/to/financials.json

免 token 即可使用（免費層 600 req/hr，本腳本一檔用 5 個 request）。
若環境有 $FINMIND_TOKEN 會自動帶上，額度較寬。

FinMind 的損益表與現金流量表是**單季值**，不是累計值，不需要還原。
資產負債表是期末餘額。全部驗證於 2026-08。
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

BASE = "https://api.finmindtrade.com/api/v4/data"
MOPS_FS = "https://mops.twse.com.tw/mops/web/t164sb04"  # 財報查詢頁，供報告引用


def fetch(dataset, stock_id, start, end=None):
    params = {"dataset": dataset, "data_id": stock_id, "start_date": start}
    if end:
        params["end_date"] = end
    req = urllib.request.Request(f"{BASE}?{urllib.parse.urlencode(params)}")
    token = os.environ.get("FINMIND_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=40) as r:
        body = json.load(r)
    if body.get("status") != 200:
        sys.exit(f"[{dataset}] FinMind 回應失敗：{body.get('msg')}")
    return body.get("data", [])


def pivot(rows):
    """[{date,type,value}] -> {date: {type: value}}"""
    out = defaultdict(dict)
    for r in rows:
        out[r["date"]][r["type"]] = r["value"]
    return out


def div(a, b):
    return round(a / b, 4) if (a is not None and b) else None


def pct(a, b):
    return round(a / b * 100, 2) if (a is not None and b) else None


def growth(cur, prev):
    return round((cur - prev) / abs(prev) * 100, 2) if (cur is not None and prev) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stock_id")
    ap.add_argument("--start", default="2024-01-01", help="起始日（預設抓 2 年以涵蓋 YoY）")
    ap.add_argument("--out", default="financials.json")
    args = ap.parse_args()
    sid = args.stock_id

    inc = pivot(fetch("TaiwanStockFinancialStatements", sid, args.start))
    bal = pivot(fetch("TaiwanStockBalanceSheet", sid, args.start))
    cfs = pivot(fetch("TaiwanStockCashFlowsStatement", sid, args.start))
    rev = fetch("TaiwanStockMonthRevenue", sid, args.start)
    info = fetch("TaiwanStockInfo", sid, args.start)

    quarters = sorted(inc.keys())
    series = {}
    for d in quarters:
        i, b = inc[d], bal.get(d, {})
        revenue = i.get("Revenue")
        net = i.get("IncomeAfterTaxes")
        equity_parent = b.get("EquityAttributableToOwnersOfParent")
        capital = b.get("CapitalStock")
        shares = capital / 10 if capital else None  # 台股面額 10 元
        cur_assets, cur_liab = b.get("CurrentAssets"), b.get("CurrentLiabilities")
        series[d] = {
            "revenue": revenue,
            "gross_profit": i.get("GrossProfit"),
            "operating_income": i.get("OperatingIncome"),
            "pretax_income": i.get("PreTaxIncome"),
            "net_income": net,
            "eps": i.get("EPS"),
            "nonoperating": i.get("TotalNonoperatingIncomeAndExpense"),
            "gross_margin": pct(i.get("GrossProfit"), revenue),
            "operating_margin": pct(i.get("OperatingIncome"), revenue),
            "net_margin": pct(net, revenue),
            "current_ratio": pct(cur_assets, cur_liab),
            "quick_ratio": pct(cur_assets - b["Inventories"], cur_liab)
            if cur_assets and cur_liab and "Inventories" in b else None,
            "debt_ratio": pct(b.get("Liabilities"), b.get("TotalAssets")),
            "roe_quarterly": pct(net, equity_parent),
            "book_value_per_share": div(equity_parent, shares),
            "operating_cash_flow": cfs.get(d, {}).get("NetCashInflowFromOperatingActivities"),
        }

    # QoQ / YoY（YoY 取前 4 季）
    for n, d in enumerate(quarters):
        for key in ("revenue", "gross_profit", "operating_income", "net_income", "eps"):
            cur = series[d][key]
            series[d][f"{key}_qoq"] = growth(cur, series[quarters[n - 1]][key]) if n >= 1 else None
            series[d][f"{key}_yoy"] = growth(cur, series[quarters[n - 4]][key]) if n >= 4 else None

    monthly = [
        {
            "year": m["revenue_year"], "month": m["revenue_month"],
            "revenue": m["revenue"], "published": m.get("create_time") or None,
        }
        for m in sorted(rev, key=lambda x: (x["revenue_year"], x["revenue_month"]))
    ]
    for n, m in enumerate(monthly):
        m["yoy"] = growth(m["revenue"], monthly[n - 12]["revenue"]) if n >= 12 else None

    payload = {
        "meta": {
            "stock_id": sid,
            "name": info[0].get("stock_name") if info else None,
            "industry": info[0].get("industry_category") if info else None,
            "source": "FinMind API",
            "source_note": "原始出處為公開資訊觀測站財報，經 FinMind 整理。單季值，非累計。",
            "mops_url": f"{MOPS_FS}?encodeURIComponent=1&run=Y&step=1&co_id={sid}",
            "unit": "新台幣元（比率為 %，EPS 為元）",
            "tier_hint": "L1（數字源自官方財報；若報告要標 L1 需在 MOPS 對得上，否則標 L2）",
        },
        "quarterly": series,
        "monthly_revenue": monthly,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    latest = quarters[-1]
    s = series[latest]
    print(f"✓ {sid} {payload['meta']['name']} → {args.out}")
    print(f"  季別 {len(quarters)} 期（{quarters[0]} ~ {latest}）｜月營收 {len(monthly)} 筆")
    print(f"  最新季 {latest}：營收 {s['revenue']/1e8:.2f} 億、毛利率 {s['gross_margin']}%、"
          f"營益率 {s['operating_margin']}%、EPS {s['eps']}")
    missing = [k for k, v in s.items() if v is None]
    if missing:
        print(f"  未取得欄位：{', '.join(missing)}")


if __name__ == "__main__":
    main()
