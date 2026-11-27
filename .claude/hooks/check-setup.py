#!/usr/bin/env python3
"""Stock-Analysis 安裝檢查：確認跑報告需要的工具與金鑰都設好了。

用法（在專案根目錄）：
  python3 .claude/hooks/check-setup.py              # 檢查全部，印出缺什麼、怎麼設
  python3 .claude/hooks/check-setup.py --skill tw   # 只檢查台股報告需要的
  python3 .claude/hooks/check-setup.py --skill us   # 只檢查美股報告需要的
  python3 .claude/hooks/check-setup.py --hook       # SessionStart hook 模式（輸出 JSON）

結束碼：0 = 必要項目都齊；1 = 缺必要項目。--hook 模式一律回 0，不擋 session。
只檢查「有沒有設」，不印出任何金鑰或信箱的值。只用標準函式庫。
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_SETTINGS = ROOT / ".claude" / "settings.local.json"
EXAMPLE = ".claude/settings.local.json.example"
TG_CONFIG = Path.home() / ".config" / "tw-stock-tg" / "config.json"
CHROME_PATHS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium"]

SETTINGS_HOWTO = (
    f"設定位置：專案的 .claude/settings.local.json（已被 .gitignore 排除，不會上傳）。\n"
    f"沒有這個檔：複製範例 `cp {EXAMPLE} .claude/settings.local.json` 再填值。\n"
    "已經有這個檔：在最外層的 \"env\" 區塊加上 \"{key}\": \"...\"（沒有 env 區塊就新增），其他內容不要動。\n"
    "改完重開 Claude Code 才會載入。")


def is_placeholder(value):
    v = (value or "").strip()
    return (not v or "example.com" in v or v.startswith("<")
            or "your" in v.lower() or "paste" in v.lower())


def read_local_env():
    """回傳 (env dict, 錯誤訊息)。只讀 env 區塊。"""
    if not LOCAL_SETTINGS.exists():
        return {}, None
    try:
        data = json.loads(LOCAL_SETTINGS.read_text("utf-8"))
    except (ValueError, OSError) as e:
        return {}, f".claude/settings.local.json 不是合法的 JSON（{e}）。請修正格式，否則 Claude Code 也讀不到設定。"
    env = data.get("env") if isinstance(data, dict) else None
    return (env if isinstance(env, dict) else {}), None


def env_status(key, local_env):
    """回傳 ok / pending（寫進檔案但這個 session 還沒載入）/ missing。"""
    if not is_placeholder(os.environ.get(key)):
        return "ok"
    if not is_placeholder(local_env.get(key)):
        return "pending"
    return "missing"


def build_checks(local_env):
    checks = []

    pdftotext = shutil.which("pdftotext") is not None
    checks.append(dict(
        skill="tw", required=True, name="pdftotext（poppler）",
        status="ok" if pdftotext else "missing",
        fix="用途：把法說會簡報與財報 PDF 轉成文字。\n"
            "macOS：brew install poppler\n"
            "Ubuntu／Debian：sudo apt install poppler-utils\n"
            "Windows：建議在 WSL 裡使用本專案，再照 Ubuntu 的指令安裝。"))

    sec = env_status("SEC_UA_EMAIL", local_env)
    sec_value = os.environ.get("SEC_UA_EMAIL") or local_env.get("SEC_UA_EMAIL") or ""
    if sec != "missing" and "@" not in sec_value:
        sec = "invalid"
    checks.append(dict(
        skill="us", required=True, name="SEC_UA_EMAIL", status=sec,
        fix="用途：SEC EDGAR 規定每個請求的 User-Agent 要帶聯絡信箱，沒帶會被回 403。\n"
            "這不是金鑰，不用申請，填你自己的信箱即可。\n"
            "規定原文：https://www.sec.gov/os/accessing-edgar-data\n"
            + SETTINGS_HOWTO.format(key="SEC_UA_EMAIL")))

    fm = env_status("FINMIND_TOKEN", local_env)
    checks.append(dict(
        skill="tw", required=False, name="FINMIND_TOKEN", status=fm,
        fix="用途：台股財務數據走 FinMind API。不設也能跑，但免費匿名額度較低，報告中途可能用盡。\n"
            "申請：到 https://finmindtrade.com/ 免費註冊，登入後在會員頁複製 API token。\n"
            + SETTINGS_HOWTO.format(key="FINMIND_TOKEN")))

    tg_ok = False
    if TG_CONFIG.exists():
        try:
            cfg = json.loads(TG_CONFIG.read_text("utf-8"))
            tg_ok = (not is_placeholder(str(cfg.get("bot_token", "")))
                     and bool(str(cfg.get("chat_id", "")).strip()))
        except (ValueError, OSError):
            tg_ok = False
    chrome = any(Path(p).exists() for p in CHROME_PATHS) or bool(
        shutil.which("google-chrome") or shutil.which("chromium"))
    checks.append(dict(
        skill="tw", required=False, name="Telegram 傳送（報告上的「傳到 TG」按鈕）",
        status="ok" if (tg_ok and chrome) else "missing",
        fix="用途：把報告轉成 PDF 傳到你的 Telegram 頻道。不用這個功能可以忽略。\n"
            "需要：Google Chrome，以及 ~/.config/tw-stock-tg/config.json（放在 repo 外）。\n"
            "步驟：.claude/skills/tw-stock-research/references/telegram-sending.md"))

    checks.append(dict(
        skill="us", required=False, name="Massive（原 Polygon.io）MCP",
        status="skill-check",
        fix="用途：美股結構化財務與股價。沒有也能跑（改用 SEC XBRL 與 Yahoo 股價）。\n"
            "這一項要在 Claude Code 裡才查得到，跑美股報告時 skill 會自己確認。\n"
            "申請與安裝步驟：README 的「Massive (Polygon) MCP」段落。"))
    return checks


LABEL = {"ok": "✅ 已設定", "missing": "未設定", "invalid": "格式不對（要是信箱）",
         "pending": "已寫入 settings.local.json，但這個 session 還沒載入，請重開 Claude Code",
         "skill-check": "ℹ️ 跑報告時檢查"}


def print_report(checks, settings_error):
    groups = [("tw", "台股報告（tw-stock-research）"), ("us", "美股報告（us-stock-research）")]
    print("Stock-Analysis 設定檢查\n")
    if settings_error:
        print(f"❌ {settings_error}\n")
    for skill, title in groups:
        items = [c for c in checks if c["skill"] == skill]
        if not items:
            continue
        print(title)
        for c in items:
            tag = "必要" if c["required"] else "選用"
            if c["status"] in ("ok", "skill-check"):
                print(f"  {LABEL[c['status']]}  {c['name']}（{tag}）")
                continue
            mark = "❌" if c["required"] else "⚠️ "
            print(f"  {mark} {c['name']}（{tag}）：{LABEL[c['status']]}")
            for line in c["fix"].splitlines():
                print(f"       {line}")
        print()
    missing = [c for c in checks if c["required"] and c["status"] != "ok"]
    if missing or settings_error:
        print(f"結果：缺 {len(missing)} 個必要項目。照上面的步驟設好後，再跑一次這個檢查。")
    else:
        print("結果：必要項目都齊了，可以開始跑報告。")


def hook_output(checks, settings_error):
    missing = [c for c in checks if c["required"] and c["status"] != "ok"]
    if not missing and not settings_error:
        return  # 都齊了就保持安靜
    names = "、".join(c["name"] for c in missing) or "settings.local.json 格式"
    detail = []
    if settings_error:
        detail.append(settings_error)
    for c in missing:
        scope = "台股報告" if c["skill"] == "tw" else "美股報告"
        detail.append(f"- {c['name']}（{scope}必要）：{LABEL[c['status']]}\n{c['fix']}")
    context = (
        "Stock-Analysis 設定檢查發現缺少必要項目：\n" + "\n".join(detail) + "\n\n"
        "請在你的第一個回覆裡，用兩三句話告訴使用者缺什麼、會影響哪種報告、怎麼設定"
        "（完整步驟可請他們執行 `python3 .claude/hooks/check-setup.py`）。"
        "只做台股的使用者可以先忽略 SEC_UA_EMAIL。使用者要你幫忙設定時，只寫入他提供的值，"
        "不要在對話中回顯 token；金鑰類的值建議讓使用者自己貼進檔案。")
    print(json.dumps({
        "systemMessage": f"Stock-Analysis 設定未完成：缺 {names}。"
                         "執行 python3 .claude/hooks/check-setup.py 查看設定步驟。",
        "hookSpecificOutput": {"hookEventName": "SessionStart",
                               "additionalContext": context},
    }, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Stock-Analysis 安裝檢查")
    ap.add_argument("--skill", choices=["tw", "us", "all"], default="all")
    ap.add_argument("--hook", action="store_true", help="SessionStart hook 模式")
    a = ap.parse_args()

    local_env, settings_error = read_local_env()
    checks = build_checks(local_env)
    if a.skill != "all":
        checks = [c for c in checks if c["skill"] == a.skill]

    if a.hook:
        hook_output(checks, settings_error)
        return 0
    print_report(checks, settings_error)
    missing = [c for c in checks if c["required"] and c["status"] != "ok"]
    return 1 if (missing or settings_error) else 0


if __name__ == "__main__":
    sys.exit(main())
