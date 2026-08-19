# 美股資料來源指南

所有結論都是 2026-08 實測驗證過的，不是推測。

## 能程序化取得的（優先於搜尋）

### SEC EDGAR → `scripts/fetch_sec.py`

```bash
python3 scripts/fetch_sec.py NVDA --out output/NVDA_20260819 --quarters 4 --n8k 25
```

美股所有官方資料的源頭，**等同台股的 MOPS 地位**。免費、無需 API key，但 **User-Agent 必須帶可聯絡信箱**，否則一律 403。

拿得到：

| 要什麼 | 在哪 |
|---|---|
| **segment 營收拆解** | **8-K 的 EX-99.2（CFO Commentary）** — 最完整，QoQ／YoY 都算好了，還有子拆解 |
| 財報數字、毛利率、non-GAAP | 8-K 的 EX-99.1（財報新聞稿） |
| 管理層關鍵發言 | EX-99.1 的 CEO quote、EX-99.2 的營運說明 |
| 完整財報與 segment note | 10-Q／10-K 本文 |
| 重大訊息（合作、發債、人事、股東會） | 8-K 本文，`items` 欄位標示 Item 編號 |

坑：

1. **8-K 的 Item 2.02 本身沒有數字**，只寫「press release is attached as Exhibit 99.1」。數字全在 exhibit。
2. **財報 8-K 可能排在很多筆之後。** NVDA 在 2026-08-19 往回數，財報 8-K（2026-05-20）排在第 5 筆。`--n8k` 要給夠。
3. **10-Q/10-K 開頭是 XBRL context 單行**，可達數萬字元。`fetch_sec.py` 已過濾，但用別的方式取檔時要小心，一個 `grep` 就會灌爆 context。
4. **segment 分類會改版。** NVDA FY27Q1 把 Compute & Networking／Graphics 改成 Data Center／Edge Computing，且在 EX-99.2 明說「transitioning to a new reporting framework」。跨季比較時要分段呈現。
5. 完整 submission 單檔可達 600KB 以上，**一律落地再處理**。

### Polygon（Claude 內建 connector，API 品牌名 Massive.com）

**只能透過 MCP 工具呼叫，沒有 API key，寫不了腳本。** 一律 `store_as` + `query_data`。

| 端點 | 狀態 | 用途 |
|---|---|---|
| `/vX/reference/financials` | 可用 | XBRL 三表（**L1′**），帶 `source_filing_url` 回溯 SEC |
| `/stocks/filings/8-K/vX/text` | 可用 | 8-K 本文，支援 FTS5 全文搜尋 |
| `/stocks/filings/8-K/vX/disclosures` | 可用 | 8-K 揭露分類 |
| `/v2/reference/news` | 可用 | 新聞（含 sentiment） |
| 行情、splits、dividends | 可用 | 股價序列、除權息 |
| `/stocks/financials/v1/*` | **NOT_ENTITLED** | 別呼叫 |

坑：

1. `/vX/reference/financials` **單筆回傳約 6K token**，`limit=1` 也一樣。務必 `store_as`。
2. **三表沒有 segment 維度**，segment 只能從 SEC exhibit 取。
3. `store_as` 後的表支援 **FTS5**：`WHERE {table} MATCH 'supply chain' ORDER BY rank`，配 `snippet()` 找 filing 內容很省 token。

### AIHOT → `scripts/aihot_query.py`

AI 生態事件的 **L3 線索層**，用法與限制見 `aihot-usage.md`。

### 不可用

- **`financial-datasets` MCP** — `~/claude/financial-datasets-mcp` 只有 `.env.example`、沒有 `.env`，API key 從未設定，所有端點實測皆失敗。不要再嘗試。

## 只能靠 web search 的

這三類是 web search 預算該花的地方：

1. **earnings call 的 Q&A 逐字稿** — SEC 與 Polygon 都沒有。找 Motley Fool、Seeking Alpha、公司 IR 的 webcast 摘要
2. **分析師目標價與 EPS 財測** — 投行報告只能透過媒體轉述。務必寫明**哪一家、什麼時間、目標價多少、基於什麼假設**
3. **產業分析與空方論述** — 研調機構觀點、社群爭議點

搜尋策略：查詢字串保持短（3–6 字），先看日期再決定要不要 fetch，發布超過半年的先跳過、超過 1 年一律不 fetch。

| 目的 | 查詢範例 |
|---|---|
| earnings call Q&A | `{ticker} Q{n} FY{year} earnings call transcript` |
| 分析師財測 | `{ticker} price target analyst {year}` |
| 空方觀點 | `{ticker} bear case risk overvalued` |
| 產業分析 | `{focus} market size forecast {year}` |

## 常見坑

1. **fiscal year ≠ calendar year。** NVDA 的 FY2027 Q1 是 2026-01-26 至 2026-04-26。報告一律同時標「FY 標示」與「實際期間」。
2. **GAAP 與 non-GAAP 差很多。** NVDA FY27Q1 GAAP EPS 2.39、non-GAAP 1.87。引用時必須標明是哪一種，不可混用。
3. **「近四季」不等於「全年」。** 聚合站常混用。
4. **三個網站寫同樣的數字不等於三個獨立來源。** 判斷是否為同一原始出處，轉載不算交叉驗證。
5. **媒體的「分析師預估」常常沒有出處。** 找不到是哪一家、什麼時候估的，就降級或不用。
