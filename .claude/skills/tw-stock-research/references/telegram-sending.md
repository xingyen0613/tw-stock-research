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

**雙擊 `reports/` 裡的 HTML 開起來 → 勾選章節 → 按「發送到 TG」。** 不必先開終端機、
也不必啟動 Claude。約 10–30 秒後按鈕下方會顯示結果。

服務由 launchd 按需啟動（見下一節）：平常沒有任何進程在跑，按下發送的那一刻才被叫起來，
閒置 120 秒後自己退出。

從 `file://` 直接開沒問題——實測 Chrome 151 下 `file://` 頁面對 `127.0.0.1:8787` 的
GET 與帶 preflight 的 POST 都會通（服務端有回 `Access-Control-Allow-Private-Network`）。
萬一哪天瀏覽器改嚴了，改從 `http://127.0.0.1:8787` 開報告即可，那是同源、永遠不會被擋。

**注意 origin 不共通**：筆記與章節勾選存在 localStorage，`file://` 和
`http://127.0.0.1:8787` 是兩個不同的 origin，各自有一份。固定用同一種方式開就不會有事，
中途換方式會看到空的筆記。

發送時會一起帶過去的東西：

- 目前的章節勾選（取消勾選的不會出現在 PDF 裡）
- 個人筆記的內容；沒寫筆記的話，筆記那一節會自動排除，不會印出空白框
- caption 是報告的標題

### 個人想法會另外發一則訊息

PDF 要點開才看得到筆記，所以寫了筆記時，服務會在 PDF 之後**再發一則純文字訊息**，
用 `reply_to_message_id` 掛在那份 PDF 底下，頻道裡直接就能讀到：

```
📝 個人想法｜<報告標題>

<筆記全文>
```

規則：

- **取消勾選「個人想法」章節＝不打算分享**：PDF 不印、訊息也不發（兩邊語意一致）
- 筆記空白或只有空格 → 不發
- 超過 Telegram 單則 4096 字上限時自動分段，後續段落串成回覆鏈接在前一段下面，順序不會亂
- 純文字、不設 `parse_mode`，筆記裡的 `*` `_` `[` 不會被當成標記語法
- 訊息發送失敗**不影響已送出的 PDF**：畫面與 log 會標出 `個人想法訊息失敗：…`，PDF 仍算成功
- 判斷全在服務端，**舊報告 HTML 不用改也有這個行為**（只是狀態列不會顯示「另發 N 則」）
- CLI `--send` 模式沒有筆記（筆記存在瀏覽器 localStorage），自然不會發這則訊息

**PDF 會留在 `reports/pdf/`**，檔名與報告 HTML 同名。重發同一份會覆蓋舊的 PDF。
這個目錄跟 `reports/` 一樣不進 git。

不想開瀏覽器、或報告是舊版模板（沒有按鈕）時走 CLI：

```bash
python3 .claude/skills/tw-stock-research/scripts/tg_bridge.py --send reports/3081_聯亞光電_研究報告_20260813.html
```

CLI 模式會發送整份報告，不含筆記。

換 port：`--port 9000`，但要同步改 `assets/report-template.html` 裡的 `BRIDGE` 常數，
以及下面 LaunchAgent plist 裡的 `SockServiceName`。

## 按需啟動的 LaunchAgent

設定檔：`~/Library/LaunchAgents/com.yen.twstock-tg.plist`

launchd 用 socket activation 守著 `127.0.0.1:8787`——它只持有 listening socket，
不跑任何進程。第一個連線進來時才啟動 `tg_bridge.py --launchd --idle 120`，程式用
`launch_activate_socket()` 接手那個已經綁好的 socket；閒置滿 120 秒後自己退出，
launchd 繼續守著 port。所以沒人用的時候是**零進程**，要用的時候自動起來。

閒置計時只在沒有請求在處理時才累加（`BridgeServer.idle_seconds()`），
所以轉 PDF 加上傳那 10–30 秒不會被誤判成閒置而中斷。

管理指令：

```bash
launchctl print gui/$(id -u)/com.yen.twstock-tg   # 看狀態
tail -f ~/Library/Logs/twstock-tg.log             # 看喚醒與發送記錄
launchctl bootout gui/$(id -u)/com.yen.twstock-tg                                    # 停用
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.yen.twstock-tg.plist     # 啟用
```

改 idle 秒數或 port 就編輯 plist 的 `ProgramArguments` / `SockServiceName`，
然後 bootout 再 bootstrap 一次。

### 實測記錄（2026-08-17）

- 請求前零進程 → `curl /api/status` → launchd 拉起、拿到 fd、綁上 8787、正常回應
- 閒置滿設定秒數後自動退出，port 由 launchd 收回，**再送請求能重複喚醒**
- `file://` 頁面對 8787 的 GET 與帶 preflight 的 POST 都通過（Chrome 151 headless）
- 力成報告轉 PDF：3.96 MB / 9 秒，遠低於 50MB 上限

## 錯誤訊息對照

| 畫面顯示 | 原因與處理 |
|---------|-----------|
| 連不到本機發送服務 | LaunchAgent 沒載入（`launchctl print gui/$(id -u)/com.yen.twstock-tg` 查），或 port 不是 8787。看 `~/Library/Logs/twstock-tg.log` 有沒有啟動失敗訊息 |
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
- 個人想法訊息（2026-08-20 加）：分段還原、回覆鏈順序、四種發／不發的判斷、
  以及「訊息失敗但 PDF 已送出」都以攔截 API 的方式測過
