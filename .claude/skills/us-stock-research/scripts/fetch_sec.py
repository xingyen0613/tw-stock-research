#!/usr/bin/env python3
"""把一檔美股最近的 SEC filings 落地成純文字，供後續解析。

SEC 要求 User-Agent 帶可聯絡信箱，否則回 403。信箱從環境變數 SEC_UA_EMAIL 讀，沒設就直接報錯。

用法：
    python3 fetch_sec.py NVDA --out output/NVDA_20260819
    python3 fetch_sec.py NVDA --out output/NVDA_20260819 --quarters 4 --n8k 25

輸出 index.json 與各 filing 的 .txt。主對話只讀 index.json，不讀 .txt 全文。
"""
import argparse, json, html, os, re, sys, time, urllib.request
from pathlib import Path

# 這個信箱是 SEC 的存取條件（流量識別用）。repo 是 public，所以不寫死在程式裡；
# 本機設在 .claude/settings.local.json 的 env（該檔不進 git）。
SEC_UA_EMAIL = os.environ.get("SEC_UA_EMAIL", "").strip()
UA = f"Stock-Analysis-Research {SEC_UA_EMAIL}"
TICKER_MAP = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}.txt"
# EX-99.1 是財報新聞稿、EX-99.2 是 CFO Commentary（segment 拆解在這裡）
WANTED_EXHIBITS = ("EX-99.1", "EX-99.2")


def get(url, retries=3):
    """SEC 要求 UA 帶信箱，且建議 <10 req/s。"""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                time.sleep(0.15)
                return raw.decode("utf-8", errors="ignore")
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def resolve_cik(ticker):
    data = json.loads(get(TICKER_MAP))
    for row in data.values():
        if row["ticker"].upper() == ticker.upper():
            return int(row["cik_str"]), row["title"]
    sys.exit(f"[ERR] 在 SEC ticker 對照表找不到 {ticker}")


def list_filings(cik, quarters, n8k):
    """回傳最近 N 季的 10-Q/10-K，以及最近 N 筆 8-K。"""
    recent = json.loads(get(SUBMISSIONS.format(cik=cik)))["filings"]["recent"]
    rows = [dict(zip(recent.keys(), vals)) for vals in zip(*recent.values())]
    periodic = [r for r in rows if r["form"] in ("10-Q", "10-K")][:quarters]
    current = [r for r in rows if r["form"] == "8-K"][:n8k]
    return periodic + current


def split_documents(raw):
    """把完整 submission 切成 (type, filename, body) 清單。"""
    out = []
    for block in re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", raw, re.S):
        t = re.search(r"<TYPE>([^\s<]+)", block)
        fn = re.search(r"<FILENAME>([^\s<]+)", block)
        body = re.search(r"<TEXT>(.*?)</TEXT>", block, re.S)
        if t and body:
            out.append((t.group(1), fn.group(1) if fn else "", body.group(1)))
    return out


def to_text(body):
    """HTML → 純文字，保留表格的列與欄邊界，否則 segment 表會被擠成一行。"""
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", body)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = re.sub(r"(?i)</tr>|<br\s*/?>|</p>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    s = re.sub(r" *\| *(\| *)+", " | ", s)          # 空儲存格塌縮
    s = re.sub(r"^\s*\|\s*|\s*\|\s*$", "", s, flags=re.M)
    s = re.sub(r"\n{3,}", "\n\n", s)
    lines = [line.strip() for line in s.splitlines()]
    # 10-Q/10-K 開頭有 XBRL context 定義，會是一條數萬字元的單行，grep 到就會灌爆 context
    lines = [ln for ln in lines if not (len(ln) > 3000 and ("us-gaap:" in ln or "xbrli:" in ln))]
    return "\n".join(lines).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--out", required=True, help="輸出目錄")
    ap.add_argument("--quarters", type=int, default=4, help="抓最近幾份 10-Q/10-K")
    ap.add_argument("--n8k", type=int, default=25, help="抓最近幾份 8-K")
    a = ap.parse_args()
    if not SEC_UA_EMAIL:
        sys.exit("[ERR] 沒設環境變數 SEC_UA_EMAIL。SEC 要求 User-Agent 帶聯絡信箱，"
                 "請在 .claude/settings.local.json 的 env 加上 SEC_UA_EMAIL")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cik, name = resolve_cik(a.ticker)
    print(f"{a.ticker} → CIK {cik} ({name})")

    index = {"ticker": a.ticker.upper(), "cik": cik, "company": name,
             "ua": UA.split()[0] + " <email redacted>", "filings": []}

    for f in list_filings(cik, a.quarters, a.n8k):
        acc = f["accessionNumber"]
        url = ARCHIVE.format(cik=cik, acc=acc)
        try:
            raw = get(url)
        except Exception as e:
            print(f"  [WARN] {f['form']} {f['filingDate']} 下載失敗：{e}")
            continue

        entry = {"form": f["form"], "filing_date": f["filingDate"],
                 "report_date": f.get("reportDate", ""), "accession": acc,
                 "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}.txt",
                 "items": f.get("items", ""), "docs": []}

        for dtype, fname, body in split_documents(raw):
            # 只落地本文與我們要的 exhibit，其餘（XBRL、圖檔、ZIP）跳過
            if dtype not in (f["form"],) + WANTED_EXHIBITS:
                continue
            text = to_text(body)
            if len(text) < 200:
                continue
            safe = f"{f['form']}_{f['filingDate']}_{dtype}".replace("/", "-")
            path = out / f"{safe}.txt"
            path.write_text(text, encoding="utf-8")
            entry["docs"].append({"type": dtype, "file": path.name,
                                  "chars": len(text), "source_file": fname})

        if entry["docs"]:
            index["filings"].append(entry)
            docs = ", ".join(f"{d['type']}({d['chars']:,}c)" for d in entry["docs"])
            print(f"  {f['form']:5} {f['filingDate']}  {docs}")

    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(d["chars"] for e in index["filings"] for d in e["docs"])
    print(f"\n落地 {len(index['filings'])} 份 filing、"
          f"{sum(len(e['docs']) for e in index['filings'])} 個文件、{total:,} chars")
    print(f"索引：{out / 'index.json'}")


if __name__ == "__main__":
    main()
