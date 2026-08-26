# 報告結構規格（美股）

**基底沿用 `.claude/skills/tw-stock-research/references/report-structure.md`** — 章節編號、卡片版型、圖表通則、配色規則、HTML 樣式要求、個人筆記與匯出區塊全部照舊，模板也用同一份 `assets/report-template.html`。

本檔只寫**與台股版的差異**。台股版沒提到的細節就照台股版做。

## 章節差異

| 節 | 台股版 | 美股版 |
|---|---|---|
| 2 | 最新一季財務摘要 | 同，但**每個利潤率與 EPS 都要標 GAAP／non-GAAP 口徑**，兩者都有就並列。期間標示為 `FY2027 Q1（2026-01-26 ～ 2026-04-26）`，**不可只寫 FY 或只寫日曆季** |
| 3 | 業務／產品別營收拆解 | **segment 營收拆解**。來源優先序 EX-99.2 > EX-99.1 > 10-Q segment note。**遇到 segment 改版：改版前後分成兩張表／兩段圖，中間加一行說明，不可硬接** |
| 4 | 官方財測與展望 | 同。美股的 guidance 通常在 EX-99.1 結尾與 EX-99.2，含下季營收中位數與正負區間，**要把區間寫出來，不要只寫中位數** |
| 6 | 法說會 Q&A 精華 | **earnings call Q&A 精華**。SEC 與 Polygon 都沒有逐字稿，全部是 web search 來的 L2/L3，**每則都要標出處與日期** |
| 7 | 法人財測彙整 | **分析師財測彙整**。務必寫明哪一家投行、什麼時間、目標價、基於什麼假設 |
| 8 | 官方未揭露項目的第三方推估 | 同。美股常見的未揭露項目：segment 毛利率、單一客戶營收占比、特定產品線 ASP |
| 9 | 產業分析（含 9.1 產業 CAGR 對照表） | 同，表格欄位照台股版。美股的研調來源以 Gartner／IDC／Dell'Oro／LightCounting／Yole／650 Group／TrendForce 為主；**規模一律標 USD B 或 USD M，並註明是 TAM、SAM 還是特定應用別的 SOM**，不同口徑不可同句比較 |

## 新增章節：AI 生態事件脈絡（美股特有，可選）

放在第 10 節「社群觀點與空方論述」之後、第 11 節「最新未驗證動態」之前。

- 資料來自 `events.json`，**只放已經回溯到 SEC 的（tier 已升級為 L1）**，按時間倒序
- 每則寫：日期、事件、**SEC 原檔連結**、對本業的意涵
- 回溯不到官方原檔的事件**不放這節**，放第 11 節「最新未驗證動態」並標 L3
- **`low_coverage: true` 時整節不出現**，並在第 13 節「資料來源與驗證紀錄」註明「AIHOT 對本標的覆蓋不足（命中 N 則），未納入 AI 生態章節」

## 圖表差異

| 圖 | 差異 |
|---|---|
| 圖 1、圖 2（segment 占比／金額） | segment 改版時**分成兩組圖**或在改版點加分隔線與註記，不可讓兩套分類共用一條時間軸 |
| 圖 3（獲利能力趨勢） | 毛利率／營益率／淨利率**同時畫 GAAP 與 non-GAAP 兩組線**，用實線／虛線區分，圖例標清楚 |
| 圖 4（營收與 EPS） | EPS 標明口徑；營收單位用**百萬美元（USD M）**，並在軸標題註明 |
| 圖 5（本益比河流圖） | 期間**只有 2 年**，EPS 用 **GAAP diluted**，Y 軸與色帶單位為 **USD**。詳見下節 |

## 圖 5 本益比河流圖：美股的資料怎麼取

計算與畫法完全沿用台股版（`scripts/fetch_pe_band.py`），差別只在資料從哪來。台股那支腳本會自己去 FinMind 抓，美股沒有等價的免費 API，**要先用 Polygon MCP 把資料湊成一份 `raw.json`，再餵給腳本的 `--from-json` 模式**：

```json
{"meta":{"ticker":"FN","name":"Fabrinet","currency":"USD","unit":"USD"},
 "prices":[{"date":"2026-08-01","close":501.06}, ...],
 "eps":[{"period":"FY2026Q3","eps":3.45,"effective_from":"2026-05-05"}, ...]}
```

```bash
python3 .claude/skills/tw-stock-research/scripts/fetch_pe_band.py \
  --from-json output/{標的}_{日期}/pe_raw.json --years 2 \
  --out output/{標的}_{日期}/pe_band.json
```

### 股價：月線 aggregates，只回溯 2 年

```
/v2/aggs/ticker/{T}/range/1/month/{起}/{迄}   params: adjusted=true
```

`close` 欄位填 **`vw`（成交量加權均價）**，那才是「月均價」；`c` 是月收盤，會被最後一天的跳動帶偏。

兩個實測到的限制：

1. **超過約 2 年就 `NOT_ENTITLED`。** 2026-08 實測 FN：2024-08 以後拿得到，2023-01～2024-08 直接回 NOT_ENTITLED。所以美股版一律 `--years 2`，並在 caption 寫明「受行情資料權限限制，區間僅涵蓋 24 個月」。日後權限升級再把年數調大即可，腳本不用改。
2. **每頁只回 5 筆**，`limit` 給多少都一樣。24 個月要跟著 `cursor` 分頁 5 次。回應會給下一頁的完整 path 與 cursor，照著呼叫就好。

### EPS：quarterly 沒有 Q4，要自己補

```
/vX/reference/financials   params: ticker, timeframe=quarterly, limit=12, order=desc, sort=filing_date
/vX/reference/financials   params: ticker, timeframe=annual,    limit=3,  order=desc, sort=filing_date
```

取 `financials_income_statement_diluted_earnings_per_share_value`（**GAAP diluted**）與 `filing_date`。

**`timeframe=quarterly` 只回 Q1–Q3。** 第四季的數字只存在於 10-K，所以：

```
Q4 EPS = 該會計年度 annual EPS − (Q1 + Q2 + Q3)
Q4 的 effective_from = 10-K 的 filing_date
```

實測 FN：FY2026 全年 13.05，Q1–Q3 為 2.66／3.11／3.45（合計 9.22）→ Q4 = 3.83，`effective_from` 用 10-K 的 2026-08-18。漏掉這一步，近四季 EPS 會少一季，本益比整條線偏高。

註兩件事：

- 四季 diluted EPS 相加與全年 diluted EPS 有微幅差異（各季加權股數不同），這是市場慣例算法，與台灣證交所一致，不必修正
- Q4 業績其實在財報 8-K 就公布了，10-K 通常晚幾天。月粒度下同屬一個月，影響可以忽略；真的踩到月底邊界時，改用該季 8-K 的日期

### 換檔日與月粒度

腳本用**當月最後一天**去比對 `effective_from`，不是 `prices` 裡的日期——月線 aggregate 的日期是月初（`2026-08-01`），拿它去比會把當月才公布的那一季整個漏掉。這個坑實測踩過：FN 2026-08 的本益比會從正確的 38.4 變成 43.08。

### Polygon 回傳體積的坑

`/vX/reference/financials` **即使加了 `store_as` 也會回一份 preview**，含完整欄位名清單（200+ 欄）加前 5 列，單次約 20K token。所以：

- `limit` 壓到真正需要的筆數（quarterly 12、annual 3 就夠算 2 年的近四季 EPS）
- 存進 workspace 後用 `query_data` 只 SELECT 需要的四個欄位，不要再呼叫一次 API

## 單位與格式

- 幣別一律 **USD**，金額單位統一用百萬美元並在表頭標 `(USD M)`，不要混用 billion／million
- **第 2 章財務摘要每一列都要標單位**，寫在「指標」欄位裡（`Revenue (USD M)`／`EPS (USD)`／`Gross margin (%)`），或在表頭統一標 `金額單位：USD M` 再對非金額列個別標示。讀者不該靠數量級猜這是千美元還是百萬美元
- SEC 表格常以 `USD thousands` 呈現，換算成 USD M 後在表格下方註明「原始 filing 單位為千美元，已換算為百萬美元」
- **速覽卡片每張都要顯示單位**（USD／USD B／倍／%）與資料日期
- **每張圖的 Y 軸標題必須含單位**（`Revenue (USD M)`、`EPS (USD)`、`Margin (%)`），雙 Y 軸兩邊都要標；**圖下 caption 再重述一次單位與幣別**，因為匯出 PDF 時讀者常只看得到圖與 caption
- 期間一律 `FY{年} Q{季}` 加實際起訖日
- 成長率標明是 QoQ 還是 YoY，不要只寫「成長 92%」
