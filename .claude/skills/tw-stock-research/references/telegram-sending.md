# 把報告發到 Telegram 頻道

## 為什麼需要一個本機服務

報告裡原本的「匯出 PDF」是呼叫 `window.print()`，PDF 是瀏覽器列印對話框產生的，
網頁的 JS 拿不到那個檔案，沒辦法自己發出去。而 bot token 也不能寫進報告 HTML
（報告會分享給別人，token 一起流出去，任何人都能用你的 bot 發訊息）。

所以轉檔與發送都放在 `scripts/tg_bridge.py`：只綁 `127.0.0.1`、只讀 `reports/` 目錄、
token 存在家目錄的設定檔。報告 HTML 完全乾淨，分享出去不會洩漏任何東西。

## 一次性設定

### 1. 準備 bot

在 Telegram 找 [@BotFather](https://t.me/BotFather) → `/newbot` → 取得 token
（形如 `123456789:AAH...`）。已經有 bot 的話直接沿用，同一支 bot 可以同時收訊息和發檔案。

### 2. 把 bot 加進公告頻道

公開頻道的發文權限一定要給管理員：

1. 頻道 → Manage Channel → Administrators → Add Admin → 搜尋你的 bot
2. 只需要勾 **Post Messages**，其他權限都可以關掉
3. `chat_id` 用頻道的 public username，含 `@`，例如 `@my_stock_notes`

私人頻道沒有 username，`chat_id` 是 `-100` 開頭的數字。取得方法：先在頻道發一則訊息，
然後把它轉發到 [@userinfobot](https://t.me/userinfobot)，它會回報來源頻道的 id。

### 3. 寫設定檔

```bash
mkdir -p ~/.config/tw-stock-tg && printf '{\n  "bot_token": "貼上 BotFather 給的 token",\n  "chat_id": "@你的頻道"\n}\n' > ~/.config/tw-stock-tg/config.json && chmod 600 ~/.config/tw-stock-tg/config.json && open -e ~/.config/tw-stock-tg/config.json
```

這行指令會建好範本並用文字編輯器打開，把兩個值填進去存檔即可。
不想寫檔的話也可以改用環境變數 `TW_STOCK_TG_BOT_TOKEN` / `TW_STOCK_TG_CHAT_ID`。

**這個檔案不要複製進專案目錄，也不要貼進任何對話。**

## 日常使用

```bash
python3 .claude/skills/tw-stock-research/scripts/tg_bridge.py
```

啟動後開 `http://127.0.0.1:8787`，會看到 `reports/` 裡所有報告的清單。
點進報告 → 勾選要發的章節 → 按「發送到 TG」。約 10–30 秒後按鈕下方會顯示結果。

**一定要從 `http://127.0.0.1:8787` 開報告**，不要雙擊檔案。從 `file://` 開的頁面
發請求到本機服務屬於跨來源請求，能不能通取決於瀏覽器版本與設定；從 localhost 開就是
同源，永遠不會有這個問題（服務端仍然放行 `file://`，只是不保證）。

發送時會一起帶過去的東西：

- 目前的章節勾選（取消勾選的不會出現在 PDF 裡）
- 個人筆記的內容；沒寫筆記的話，筆記那一節會自動排除，不會印出空白框
- caption 是報告的標題

**PDF 會留在 `reports/pdf/`**，檔名與報告 HTML 同名。重發同一份會覆蓋舊的 PDF。
這個目錄跟 `reports/` 一樣不進 git。

不想開瀏覽器、或報告是舊版模板（沒有按鈕）時走 CLI：

```bash
python3 .claude/skills/tw-stock-research/scripts/tg_bridge.py --send reports/3081_聯亞光電_研究報告_20260813.html
```

CLI 模式會發送整份報告，不含筆記。

換 port：`--port 9000`，但要同步改 `assets/report-template.html` 裡的 `BRIDGE` 常數。

## 錯誤訊息對照

| 畫面顯示 | 原因與處理 |
|---------|-----------|
| 連不到本機發送服務 | `tg_bridge.py` 沒在跑，或 port 不是 8787 |
| 還沒設定 bot_token / chat_id | 設定檔沒填或路徑不對，看上面第 3 步 |
| Telegram 回應 401：Unauthorized | token 錯了或已被 BotFather 撤銷 |
| Telegram 回應 400：chat not found | `chat_id` 打錯；公開頻道要含 `@`，私人頻道是 `-100` 開頭數字 |
| Telegram 回應 400：not enough rights | bot 不是頻道管理員，或沒給 Post Messages |
| PDF 超過 Telegram bot 的 50MB 上限 | 取消勾選幾個章節再發 |
| 拒絕來自 https://… 的請求 | 有非本機頁面試圖呼叫這個服務，已被擋下（正常的防護行為） |

## 實測過的行為

- headless Chrome 轉檔約 3 秒，中文字型與四張 Chart.js 圖表都正常渲染
- `--user-data-dir` 一定要搭配 `--incognito`：只帶前者時 Chrome 印完 PDF 就掛住不退出
  （PDF 已寫好，但行程要等到被 kill），加了 incognito 才會正常結束
- 章節過濾、筆記注入、multipart 上傳格式（含中文 caption 與 PDF bytes 完整性）都驗證過
- 路徑穿越（`/r/../../.gitignore`）回 404；非 localhost 的 Origin 一律 403
