#!/usr/bin/env python3
"""用文字座標拆解 PDF 單頁的圖表標籤，取代「轉成 PNG 目視核對」。

`pdftotext -layout` 會把圖表標籤按視覺位置攤平，堆疊長條圖常出現同一組數字
在版面左緣被重印一次（偽重複），光看攤平後的文字無法判斷是兩組資料還是一組。
`-bbox-layout` 保留每個 word 的座標，依 x 分群後就能對齊 X 軸標籤，
把每一組數值歸給正確的欄位，並認出偽重複。

實測體積（法說會簡報單頁）：本腳本輸出 ~500 chars，同一頁轉 PNG 讀進 context
約 362,000 chars——差 700 倍，而且座標可稽核，比目視結論更硬。

用法：
    python3 pdf_chart_probe.py <pdf> <page>                # 預設抓含數字的 word
    python3 pdf_chart_probe.py <pdf> <page> -p '%$'        # 只抓百分比
    python3 pdf_chart_probe.py <pdf> <page> --all          # 印出整頁所有 word 分群
    python3 pdf_chart_probe.py <pdf> <page> -t 40          # 放寬 x 分群容差（預設 25pt）

輸出：X 軸標籤候選（頁面最下緣那排）＋ 依 x 座標分群的數值，
      內容完全相同的群會標成「⚠ 與 x≈N 重複」。
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict

WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>'
)


def words(pdf, page):
    """回傳 [(x, y, text)]，x 為 word 左緣、y 為上緣。"""
    try:
        xml = subprocess.run(
            ["pdftotext", "-bbox-layout", "-f", str(page), "-l", str(page), pdf, "-"],
            capture_output=True, text=True, check=True,
        ).stdout
    except FileNotFoundError:
        sys.exit("找不到 pdftotext，請先安裝 poppler")
    except subprocess.CalledProcessError as e:
        sys.exit(f"pdftotext 失敗：{e.stderr.strip()}")
    out = []
    for x0, y0, _x1, _y1, t in WORD_RE.findall(xml):
        t = t.strip()
        if t:
            out.append((float(x0), float(y0), t))
    return out


def cluster(items, tol):
    """依 x 分群，回傳 {群心 x: [(y, text)]}。"""
    groups = defaultdict(list)
    for x, y, t in sorted(items):
        for k in groups:
            if abs(k - x) < tol:
                groups[k].append((y, t))
                break
        else:
            groups[x].append((y, t))
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("page", type=int)
    ap.add_argument("-p", "--pattern", default=r"\d",
                    help="要納入分群的 word 正則（預設含數字者）")
    ap.add_argument("-t", "--tol", type=float, default=25.0, help="x 分群容差 pt")
    ap.add_argument("--all", action="store_true", help="印出整頁所有 word")
    args = ap.parse_args()

    ws = words(args.pdf, args.page)
    if not ws:
        sys.exit(f"第 {args.page} 頁抽不到任何文字——這頁可能是純圖片，"
                 f"確認過再考慮轉圖，並先跟使用者說明為什麼非轉不可。")

    pat = re.compile(args.pattern)
    picked = ws if args.all else [w for w in ws if pat.search(w[2])]
    if not picked:
        sys.exit(f"第 {args.page} 頁沒有符合 /{args.pattern}/ 的 word（全頁共 {len(ws)} 個）")

    # 底部區域按 y 分行印出，X 軸標籤就在其中一行（最下面那行通常是頁尾版權，
    # 不要自動剔除——猜錯比多印一行貴，讓讀的人自己挑）
    ymax = max(y for _x, y, _t in ws)
    bottom = [(y, x, t) for x, y, t in ws if y > ymax * 0.80]
    rows = defaultdict(list)
    for y, x, t in sorted(bottom):
        for k in rows:
            if abs(k - y) < 8:
                rows[k].append((x, t))
                break
        else:
            rows[y].append((x, t))
    if rows:
        print("底部區域各行（X 軸標籤在其中一行，最下行多半是頁尾）：")
        for k in sorted(rows)[:3]:
            line = "  ".join(f"{t}@{x:.0f}" for x, t in sorted(rows[k]))
            print(f"  y={k:<6.0f} {line[:200]}")
        print()

    groups = cluster(picked, args.tol)
    rendered, numsets = {}, {}
    for k in sorted(groups):
        rendered[k] = " ".join(t for _y, t in sorted(groups[k]))
        # 從黏字中挖出數值（`Sip/Module11%` → 11%），用集合比對才認得出重印
        numsets[k] = frozenset(re.findall(r"\d+(?:\.\d+)?%?", rendered[k]))

    print(f"依 x 座標分群（容差 {args.tol:g}pt，由左至右）：")
    for k in sorted(rendered):
        dup = [j for j in rendered
               if j != k and len(numsets[k]) >= 2
               and numsets[k] <= numsets[j] and (numsets[k] != numsets[j] or j < k)]
        flag = f"   ⚠ 數值被 x≈{dup[0]:.0f} 涵蓋，其一為版面重印" if dup else ""
        print(f"  x≈{k:<8.1f} {rendered[k]}{flag}")

    print(f"\n共 {len(rendered)} 群 / {len(picked)} 個 word。"
          f"\n對齊方式：把每一群的 x 跟 X 軸標籤那行的 x 比對，最接近者即為該群所屬欄位；"
          f"\n落在所有軸標籤之外的群，通常是版面溢位的重印，不是獨立資料。"
          f"\n分群被切太碎（例如標籤黏成一個 word）就加大 -t 容差重跑，不要轉圖。")


if __name__ == "__main__":
    main()
