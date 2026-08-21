---
name: us-stock-research
description: 產出美股個股的深度研究報告（單檔 HTML，含來源連結與圖表）。使用者只丟一個美股代號或公司名稱（例如「NVDA」「幫我看一下輝達」「Broadcom」），或再加上想深入的產業主題（例如「AI 資料中心」「客製化 ASIC」「光通訊」），就用這個 skill。它會抓最近幾季的 SEC 財報與 8-K、拆解各業務別（segment）營收占比、彙整分析師財測與空方論述，再跑一次獨立驗證，最後輸出帶引用連結的 HTML 報告。只要使用者提到美股代號、SEC filing、10-Q／10-K／8-K、earnings call、財報摘要、分析師目標價，就主動使用本 skill，即使他沒說「報告」兩個字。台股請改用 tw-stock-research。
---

# 美股個股研究報告

產出一份**可稽核**的個股研究報告。核心價值不是「寫得漂亮」，而是**每一個數字都能追回來源，而且經過第二輪獨立驗證**。寧可少寫一個數字，也不要寫一個查不到出處的數字。

術語一律照專案根目錄的 `UBIQUITOUS_LANGUAGE.md`。

## 輸入

1. `{標的}` — 美股代號或公司名稱（必填）
2. `{focus}` — 想深入的產業／技術主題（選填）

`{focus}` 沒給的話，**不要問使用者**。自己從最新一季的 segment 拆解判斷 1–2 個主導營收的主題，並在報告開頭說明「本次自動選定的產業主題為 X，因為它佔最新一季營收 Y%」。

## 資料來源分級

| 等級 | 定義 | 來源 |
|---|---|---|
| **L1 官方** | 公司自己發布的 | SEC 的 10-K／10-Q／8-K 本文與 exhibit（EX-99.1 財報新聞稿、EX-99.2 CFO Commentary）、公司 IR 網站 |
| **L1′ 官方衍生** | 第三方結構化的 L1，且帶得回原始 filing 連結 | Polygon `/vX/reference/financials`（XBRL 三表） |
| **L2 法人／研調** | 專業機構分析或財測 | 分析師目標價、研調機構報告 |
| **L3 媒體／社群** | 二手轉述或個人觀點 | aihot、財經媒體、論壇 |

衝突時 **L1 > L1′ > L2 > L3**。各來源能拿什麼、有什麼坑，讀 `references/sources-us.md`。

## 資料新鮮度上限

除了財報的「最近 4 季」序列之外，**所有第三方資料一律以半年內為主，超過 1 年一律不用**。分析師財測、目標價、產業分析、社群觀點都受此限，引用時一律標註發布日期。

## 工作流程

分五個 Phase，**不要邊查邊寫**。Phase A、B 全部派 subagent，主對話不自己下場查資料。

### Phase A — 官方資料

**A-1 SEC filings 落地（Haiku）**

```bash
python3 .claude/skills/us-stock-research/scripts/fetch_sec.py {標的} --out output/{標的}_{日期} --quarters 4 --n8k 25
```

一次拿齊最近 4 份 10-Q/10-K 與最近 25 份 8-K，切出本文與 EX-99.1／EX-99.2 落成 `.txt`，並產出 `index.json`。**只回報 `index.json` 的路徑與 filing 清單，不要把任何 `.txt` 內容貼回來。**

`--n8k` 一定要夠大，**財報 8-K（含 Item 2.02）可能排在很多筆之後**；抓不到帶 EX-99.2 的那份就把 `--n8k` 加大重跑。

**A-2 量化財務（Haiku）** — Polygon MCP，見下方「Polygon 鐵則」。落成 `financials.json`。財務比率用原始科目自己算，不要另外搜尋。

**A-3 segment 拆解（Sonnet）** — 讀 A-1 落地的 `.txt`，抽出各 segment 營收與占比、公司財測、管理層關鍵發言，落成 `segments.json`。

**優先序：EX-99.2（CFO Commentary）> EX-99.1（財報新聞稿）> 10-Q 的 segment note。** EX-99.2 通常已經把 QoQ／YoY 算好，而且有子拆解。

**segment 分類會改版。** 例如 NVDA 在 FY27Q1 從 Compute & Networking／Graphics 改成 Data Center／Edge Computing。遇到改版：在 `note` 記下新舊分類名稱，圖表分段呈現，**不要為了讓圖表連續而硬套成同一分類**。

**A-4 aihot 事件檢索（主對話直接跑，不派 agent）** — 純本地查詢，成本極低：

```bash
python3 .claude/skills/us-stock-research/scripts/aihot_sync.py          # 先收增量
python3 .claude/skills/us-stock-research/scripts/aihot_query.py {標的} --days 180 --out output/.../events.json
```

輸出若標 `low_coverage: true`（命中 < 5），**跳過報告的 AI 生態章節並註明「AIHOT 對本標的覆蓋不足」**，不要硬湊。詳見 `references/aihot-usage.md`。

### Phase B — 非官方分析（三個 Sonnet agent 平行）

- **B-1 分析師財測** — 目標價、當年度／次年度 EPS 與營收預估、評等；以及官方不揭露的拆解（segment 毛利率、單一產品 ASP、市占率）
- **B-2 產業分析** — `{focus}` 相關的產業趨勢與市場規模。**必須交出一份產業 CAGR 清單，不是可選項**，規格見下方「產業 CAGR 要求」
- **B-3 空方與 earnings call Q&A** — **一定要找空方觀點，只有多方的報告是壞報告**。earnings call 的 Q&A 逐字稿只能靠 web search（SEC 與 Polygon 都沒有）

各自落成一個 JSON 檔，回報路徑與摘要。

### Phase C — 結構化（主對話自己做，強制中間產物）

把 Phase A、B 的產物合併成 `data.json`。**用腳本合併，不要把來源 JSON 全部 Read 進 context 再手工拼。** 合併腳本寫在該次的 output 目錄下（例如 `output/{標的}_{日期}/merge_data.py`），跑完只讀它印出的摘要（筆數、tier 分布、缺 source_url 數）。

合併時務必做這三件事（都是實跑踩過的坑）：

1. **統一期別寫法。** Polygon 回 `2026 Q1`、segment agent 回 `FY2026 Q1`、有的還帶括號註記（`FY2026 Q4 (standalone)`）。不正規化的話同一季會在圖表上變成兩個點。寫一個 `norm_period()` 全部轉成 `FY{年} Q{季}`。
2. **金額單位統一成百萬美元。** SEC 表格常是千美元（`USD thousands`），Polygon 是元。混用會讓圖表差 1000 倍。
3. **缺 `source_url` 的要留 note 說明為什麼缺**，不要留空就當作有來源。實測 Polygon 有些季度就是沒有 `source_filing_url`，而那幾期的財報又不在本次落地範圍內。

**Phase B 的 agent 若失敗需要重派，重派前先確認前一個 agent 有沒有留下同名檔案。** 實測發生過：第一個 agent 把工作轉派給子 agent 後就回報結束（檔案還沒生成），主對話判定失敗而重派，結果那個子 agent 後來也把檔案寫出來，兩者競爭寫入同一路徑。重派時在 prompt 裡明寫「你必須自己完成，不要派 subagent」。

```json
{
  "meta": { "ticker": "NVDA", "name": "NVIDIA", "focus": "AI 資料中心", "as_of": "2026-08-19" },
  "datapoints": [
    { "id": "dp001", "period": "FY2027Q1", "segment": "Data Center", "metric": "revenue",
      "value": 75246, "unit": "USD_M", "tier": "L1",
      "source_url": "https://www.sec.gov/Archives/edgar/data/1045810/0001045810-26-000051.txt",
      "source_name": "2026/05/20 8-K EX-99.2 CFO Commentary", "source_date": "2026-05-20",
      "is_estimate": false, "note": "" }
  ]
}
```

`segment` 為公司整體時填 `"company"`。`is_estimate: true` 代表預測值。

**產業 CAGR 也要進 `datapoints`**，不要只留在 B-2 的 JSON 裡：`metric: "cagr"`、`period` 填期間（`"2025-2030"`）、`unit: "%"`、`segment` 填市場範圍（`"AI accelerator"`）、`is_estimate: true`、`note` 記層級與該期間的起訖市場規模。合併腳本要一併處理，漏掉的話驗證 agent 看不到這些數字。

**此處執行線索回溯**：`events.json` 每則事件拿專有名詞去 grep A-1 落地的 8-K `.txt`——
- 對得到 → `tier` 升級 `L3` → `L1`，`source_url` 換成 SEC 連結，寫進報告正文
- 對不到 → 維持 `L3`，只能放「最新未驗證動態」區

### Phase D — 驗證（Opus subagent）

開 subagent 讀 `agents/verifier.md`，把 `data.json` 與 A-1 的 `.txt` 路徑交給它。**驗證 agent 回溯時讀 `.txt`，不讀原始 submission、更不讀網頁截圖**，用 `grep -n` 定位後只讀命中前後幾行。

驗證跑一次就好。有疑慮的項目不要偷偷刪掉：能修就修並記在驗證紀錄區，修不掉就移到「最新未驗證動態」或標紅註明來源矛盾。**驗證沒跑完，不要輸出報告。**

### Phase E — 輸出、用量與 runlog

報告 HTML 寫到**專案根目錄**的 `reports/`（絕對路徑，不要寫到 skill 自己的目錄底下），用 `SendUserFile` 送出（`display: "render"`）。

**不要用瀏覽器工具開來截圖確認**（一張截圖約 35K token，使用者從 SendUserFile 看到的畫面一樣）。用 grep 自查：

```bash
grep -c "new Chart" report.html          # 圖表數量
grep -o 'id="c[0-9]"' report.html        # canvas id 齊全
grep -c "{{" report.html                 # 應為 0
grep -o 'data-report="[^"]*"' report.html # 應為實際的 代號-日期
grep -c "<figure>" report.html           # 應與 new Chart 數量一致
```

**`<figure>` 這項曾經出過事故**：報告把 `<div class="cap">` 直接塞進 `<div class="chartbox">` 內部，沒有用 `<figure>` 包起來。`.chartbox` 是 `height:340px` 固定高度容器，Chart.js 的 canvas 會把 340px 填滿，caption 文字被擠出框外、又不會撐開父層高度，於是跟下一段內容重疊、看起來像亂碼。**每張圖一律照模板結構**：`<figure><div class="chartbox"><canvas id="cN"></canvas></div><div class="cap">...</div></figure>`——`.cap` 永遠是 `.chartbox` 的外層兄弟元素，絕不能寫進 `.chartbox` 裡面。

接著跑用量統計，並把表格貼在 session 中回覆：

```bash
python3 .claude/skills/tw-stock-research/scripts/token_report.py --tools
```

**最後記 runlog**（這步不可省，它是日後迭代的唯一依據）：

```bash
python3 .claude/skills/us-stock-research/scripts/runlog.py add \
  --skill us-stock-research --ticker {標的} --tokens {總量} --duration {分鐘} \
  --issues '[{"phase":"B-3","type":"source_missing","detail":"...","action":"..."}]'
```

`issue.type` 只能是 `source_missing`／`api_not_entitled`／`parse_failed`／`rate_limited`／`data_conflict`／`token_spike`／`other`。**這次沒卡住就傳空陣列**，不要不記。使用者想看常見問題時跑 `runlog.py summary --verbose`。

## 產業 CAGR 要求（B-2 的硬性交付）

使用者要的是看懂「這家公司所處的每一段產業環節長多快」，所以不要只給一個籠統的總市場數字，能拆多細就拆多細，至少涵蓋三個層級中的兩個：

| 層級 | 例子 |
|---|---|
| 全產業／終端市場 | global data center capex、AI accelerator TAM、optical transceiver market |
| 次市場／應用別 | training vs inference accelerator、800G/1.6T transceiver、hyperscaler vs enterprise |
| 產品／元件／材料 | HBM、CoWoS capacity、DSP、EML laser、liquid cooling CDU |

每一筆 CAGR 都要帶齊：**範圍定義／起訖年份／CAGR%／該期間的起點與終點市場規模／研調機構／發布日期／來源連結**。「年增 30%」不是 CAGR，缺起訖年份的數字不要收。

- **禁止自己拿兩個年份的市場規模回推 CAGR 再當成研調機構的數字。** 真的只有兩端數據時可以自算，但要標明「本報告自算」並附上代入值
- 同一市場多家機構（Gartner、IDC、Dell'Oro、LightCounting、Yole、650 Group、TrendForce…）常差很多，**全部並列**，並說明分歧來自什麼定義差異（含不含服務、產值 vs 出貨量、TAM vs SAM）
- **TAM／SAM／SOM 要分清楚**，不同口徑的數字不可放在同一句話裡比較
- 幣別一律標明（多數為 USD B／USD M），受「資料新鮮度上限」約束

## SEC 處理鐵則

1. **完整 submission 一律落地成 `.txt` 再處理，不進 context。** 單份 8-K 的完整提交檔可達 600KB 以上，10-Q 純文字約 14 萬字元（≈35K token）。
2. **grep 前先確認行長。** 10-Q/10-K 開頭的 XBRL context 是單行數萬字元（`fetch_sec.py` 已過濾，但別的來源不一定）。用 `grep -o` 或 `cut -c1-200` 限制輸出寬度。
3. **UA 必須帶信箱**，否則 403。`fetch_sec.py` 已內建，可用環境變數 `SEC_UA_EMAIL` 覆寫。
4. **8-K 的 Item 2.02 本身沒有數字**，只寫「詳見 Exhibit 99.1」。數字在 EX-99.1／EX-99.2，一定要看 exhibit。

## Polygon 鐵則

1. **主對話絕對不要自己呼叫 `/vX/reference/financials`，一定要派 A-2 subagent。** 這個端點是 200 欄的寬表，`store_as` 的 preview 會把整張表印出來 — 實測 5 季 × 200 欄約吃掉 **25K token**，`store_as` 擋不住這一下。派 subagent 是為了讓這筆開銷燒在 subagent 的 context 裡，主對話只收 `financials.json` 的路徑。
2. **存完之後一律用 `query_data` 下 SQL 取欄位**，精簡輸出約 400 token。可照抄：

```sql
SELECT fiscal_year || ' ' || fiscal_period AS period, start_date, end_date,
  ROUND(financials_income_statement_revenues_value/1e6) AS revenue_m,
  ROUND(financials_income_statement_gross_profit_value/1e6) AS gross_m,
  ROUND(100.0*financials_income_statement_gross_profit_value/financials_income_statement_revenues_value,1) AS gm_pct,
  ROUND(financials_income_statement_operating_income_loss_value/1e6) AS op_m,
  ROUND(financials_income_statement_net_income_loss_value/1e6) AS net_m,
  financials_income_statement_diluted_earnings_per_share_value AS eps_diluted,
  source_filing_url
FROM {table} ORDER BY end_date DESC
```

3. **`source_filing_url` 可能是空的**（實測 NVDA FY26Q4 那季就沒有）。缺的季度要從 A-1 的 SEC `index.json` 找同期 filing 補上，**不可以留空就當作有來源**。
4. 可用的是 `/vX/reference/financials`、`/stocks/filings/8-K/vX/text`、`/stocks/filings/8-K/vX/disclosures`、`/v2/reference/news`、行情類端點。
5. **`/stocks/financials/v1/*` 系列是 NOT_ENTITLED**，不要浪費呼叫。
6. Polygon 的三表是 **L1′**，引用時 `source_url` 用 `source_filing_url`（指向 SEC）。**用它與 EX-99.1 的數字交叉對帳**：實測 NVDA FY27Q1 兩邊毛利率都是 74.9%，對不上就是有一邊抓錯期間。
7. `financial-datasets` MCP **沒有 API key、完全不可用**，不要嘗試。
8. 存進 workspace 的表**支援 FTS5 全文搜尋**，查 8-K 內容時很省 token：`WHERE {table} MATCH 'SB Energy' ORDER BY rank`，配 `snippet()` 只取命中片段。

## 模型分配

| 任務 | 模型 | 理由 |
|---|---|---|
| A-1 SEC 落地、A-2 量化財務 | Haiku | 照指令跑腳本／API，不需要判斷 |
| A-3 segment 拆解、B-1／B-2／B-3 | Sonnet | 要讀懂文件、判斷分類與可信度 |
| Phase D 驗證 | Opus | 要能發現矛盾，且必須 fresh context |
| Phase C 結構化、Phase E 輸出 | 主對話 | 需要全局判斷 |

## 派工合約（每個 subagent 的 prompt 都要有）

1. **目標與動機** — 要什麼、為什麼要
2. **驗收條件** — 什麼叫做完
3. **回報格式** — 只回結論與檔案路徑／行號，長產物寫檔回傳路徑，**不回貼原文**

## 三條不可妥協的規則

1. **每個數字都要有 `source_url` 與 `tier`。** 湊不出來源的數字就不要寫。
2. **驗證沒跑完不輸出報告。**
3. **一定要有空方觀點。**

## 報告免責

報告結尾固定放：本報告由 AI 彙整公開資訊產出，僅供研究參考，不構成投資建議；所有數字請以公司official filing 為準。
