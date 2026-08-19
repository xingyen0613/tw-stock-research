# Ubiquitous Language

本專案（台股／美股個股研究報告）的共同語彙。撰寫 skill、派工 prompt、報告章節與 commit message 時一律使用「Term」欄的說法。

## 資料分級

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **L1** | 公司自己發布的原始資料（台股：MOPS 法說會簡報、財報；美股：SEC 的 10-K／10-Q／8-K 與其 exhibit、公司 IR 網站） | 官方資料、一手資料 |
| **L1′** | 第三方對 L1 做結構化後的衍生資料，且回傳帶得回原始 filing 連結（目前僅指 Polygon `/vX/reference/financials` 的 XBRL 三表） | 準官方、半官方、L1.5 |
| **L2** | 專業機構的分析或財測（券商目標價、研調機構報告） | 法人資料、專業來源 |
| **L3** | 二手轉述或個人觀點（aihot、財經媒體、論壇、社群） | 非官方、小道消息 |
| **tier** | 一筆 **datapoint** 被標上的分級標籤，值域為 `L1`／`L1'`／`L2`／`L3` | level、等級欄位 |

衝突時 **L1 > L1′ > L2 > L3**，永遠不用低階覆蓋高階。

## 資料來源

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Polygon** | Claude 內建掛載的市場資料 connector（UUID `e792e1af-…`，API 品牌名 Massive.com） | Massive、Massive.com、那個 UUID connector、內建 finance 工具 |
| **SEC submission** | SEC EDGAR 上一次申報的完整提交檔（單一 `.txt`，內含本文與全部 exhibit） | SEC 原檔、EDGAR 檔案 |
| **exhibit** | SEC submission 內的附件，本專案主要取 `EX-99.1`（財報新聞稿）與 `EX-99.2`（CFO Commentary） | 附件、附錄 |
| **aihot** | 第三方中文 AI 資訊 skill，本專案中**只作為 L3 線索層**，不作為資料源 | AI 新聞源、資訊源 |
| **FinMind** | 台股量化財務 API，台股報告的 L1′ 等價物 | — |

## 報告產製

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Phase A** | 官方資料蒐集階段（A-1 filings 落地、A-2 量化財務、A-3 segment 拆解、A-4 aihot 事件檢索） | 第一階段、資料蒐集 |
| **Phase B** | 非官方分析階段（B-1 分析師財測、B-2 產業分析、B-3 空方與 Q&A） | 第二階段 |
| **Phase C** | 結構化階段，把 Phase A／B 產物合併成 `data.json`，並執行**線索回溯** | 整併、合併階段 |
| **Phase D** | 獨立驗證階段，由 fresh-context 的 Opus subagent 執行 | 檢查、複核 |
| **Phase E** | 輸出階段：HTML 報告、token 用量、**runlog** | 產出、收尾 |
| **datapoint** | 報告中一個可稽核的數字，必帶 `tier`、`source_url`、`source_date`、`is_estimate` | 數據、資料點、指標 |
| **segment** | 公司自行揭露的業務別／產品別（例如 NVDA 的 Data Center、Gaming） | 業務別、部門、事業群、product line |
| **focus** | 本次報告要深入的產業／技術主題（例如 CoWoS、光通訊） | 主題、題材 |
| **verifier** | Phase D 的驗證 subagent，只回溯落地的 `.txt`，不讀原始 submission | 檢查 agent、review agent |

## aihot 檢索

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **snapshot** | aihot `/selected/snapshot` 端點取得的**當前全部精選**完整副本，不受 24h／7d 時間窗限制 | 快照、全量、備份 |
| **changes** | aihot `/selected/changes` 端點的增量變更流，用 **sync cursor** 續接 | 增量、差異 |
| **sync cursor** | snapshot 第一頁取得的同步水位，翻頁期間恆定，翻完才用來調 changes | cursor（單獨使用會與 nextPage 混淆） |
| **nextPage** | snapshot 的翻頁游標，只在本輪快照內有效 | 分頁 cursor |
| **精選池** | `mode=selected`，AIHOT 高門檻策展後的集合 | selected、精選 |
| **全量池** | `mode=all`，最近公開動態，語義上**不等於**當前全部精選 | all、全部 |
| **weight** | 本專案自行計算的排序權重：`keyword_hits × exp(-days_ago / 45)` | 分數、熱度 |
| **score** | aihot 回傳的 0–100 欄位，區分度低（p50 72／p90 79），**本專案不用它排序** | 評分、權重 |
| **event** | aihot 命中的一則事件，`events.json` 的一筆 | 新聞、消息、item |
| **線索回溯** | 把一則 **event** 拿去 SEC filing 找官方原檔：找到就升級成 **L1** 寫進正文，找不到就降到「最新未驗證動態」標 **L3** | 交叉驗證、比對 |

## Runlog

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **runlog** | 每次產報告 append 一筆的結構化紀錄（`reports/runlog/runs.jsonl`），供跨次聚合常見問題 | 日誌、log、紀錄檔 |
| **issue** | runlog 中一筆「這次卡住或降級」的紀錄，必帶 `phase`、`type`、`action` | 問題、錯誤、bug |
| **issue.type** | issue 的固定枚舉：`source_missing`／`api_not_entitled`／`parse_failed`／`rate_limited`／`data_conflict`／`token_spike`／`other` | 分類、類別 |

## Relationships

- 一份**報告**由一組 **datapoint** 構成，每個 **datapoint** 恰好帶一個 **tier**
- 一個 **segment** 的營收數字是一筆 **tier = L1** 的 **datapoint**，來源是某次 **SEC submission** 的 **exhibit**
- 一則 **event** 經過**線索回溯**後，要嘛升級成 **L1 datapoint**，要嘛保留為 **L3**，不存在第三種結果
- 一次 **snapshot** 產生一個 **sync cursor**，之後的每次 **changes** 消費並更新它
- 一次報告產製產生恰好一筆 **runlog**，其中可含零到多個 **issue**

## Example dialogue

> **Dev：** NVDA 的 Data Center 營收，我從 Polygon 的三表拿得到嗎？
>
> **Domain expert：** 拿不到。**Polygon** 給的是 **L1′**，只有公司整體的損益、資產負債、現金流，沒有 **segment** 維度。**segment** 只存在於 **SEC submission** 的 **EX-99.2**，那是 **L1**。
>
> **Dev：** 那 aihot 上看到「NVDA 跟 SB Energy 合作」這條，可以直接寫進報告嗎？
>
> **Domain expert：** 它現在是一則 **L3** 的 **event**。要先做**線索回溯** — 去 8-K 找得到官方原檔，就升級成 **L1** 寫進正文並引 SEC 連結；找不到就只能放「最新未驗證動態」，維持 **L3**。
>
> **Dev：** 排序我直接用 aihot 回傳的 score 就好吧？
>
> **Domain expert：** 不行，**score** 的 p50 是 72、p90 是 79，區分度太低，aihot 自己也禁止拿它排序。用我們自己算的 **weight**，時間衰減半衰期 45 天。
>
> **Dev：** 了解。那如果 **EX-99.2** 這次解析失敗呢？
>
> **Domain expert：** 那就在 **runlog** 記一筆 **issue**，`type` 填 `parse_failed`，寫清楚降級動作。累積幾次之後聚合就看得出來是不是某類公司的版型都吃不下。

## Flagged ambiguities

- **「Polygon」有三個叫法** — 對話中出現過「Polygon」「Massive.com」「那個 UUID connector」，指的是同一個 connector。一律稱 **Polygon**，並在文件首次出現處註明其 API 品牌名為 Massive.com。
- **「cursor」在 aihot 有兩種** — **sync cursor**（同步水位）與 **nextPage**（翻頁）互不相通，混用會造成副本缺條。禁止單獨使用「cursor」一詞。
- **「report」有兩種** — aihot API 的 `report` 指它的**日報**，本專案的「報告」指**個股研究報告**。提到 aihot 的日報時一律寫「aihot 日報」。
- **「score」與 weight** — 前者是 aihot 給的、本專案不用；後者是我們算的排序依據。不可互相代稱。
- **「L1」跨市場語義一致但來源不同** — 台股指 MOPS，美股指 SEC。定義統一為「公司自己發布的」，不要寫成「MOPS 資料」這種綁市場的說法。
- **「精選池」不等於「全量池」** — `mode=all` 是最近公開池，不是「當前全部精選」；當前全部精選只能從 **snapshot** 取得。
