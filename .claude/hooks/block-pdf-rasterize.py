#!/usr/bin/env python3
"""PreToolUse hook：擋掉把 PDF 轉成圖檔、以及把圖檔讀進 context 的行為。

起因：2026-08-14 力成(6239)報告的 A-3 subagent 為了核對堆疊長條圖的標籤，
把簡報頁轉成 PNG 目視比對，9 次 Read 吃掉 326 萬 chars（≈130 萬 token），
佔該 agent 工具回傳量的 97.4%、整份報告成本的 13.9%。

當時 SKILL.md 已有「PDF 處理鐵則」，但那條規則寫在 SKILL.md 裡，
而 subagent 有獨立 context 不會讀它——派工 prompt 沒帶到，規則等於不存在。
文件層面已補（派工合約列為必帶段落），這個 hook 是不依賴 agent 自律的第二道。

正解是 scripts/pdf_chart_probe.py，用 pdftotext -bbox-layout 的座標分群對齊
X 軸標籤，同一頁輸出約 850 chars，是轉圖的 1/400，且結論可稽核。

逃生門：真的需要看圖時，在專案根目錄 touch .claude/.allow-image-read，
看完刪掉。刻意做成留痕跡的檔案而不是環境變數，才不會被忘在啟用狀態。
"""

import json
import re
import sys
from pathlib import Path

# 只在「指令位置」比對：行首、或 ; && || | $( ` 之後（允許前置 env 賦值）。
# 這樣 grep pdftoppm、commit message 裡提到它、註解裡寫它都不會被誤擋——
# 第一版沒做這個區分，連本次修補的 commit message 都擋掉了。
CMD_POS = r"(?:^|[\n;&|`]|\$\()[ \t]*(?:\w+=\S*[ \t]+)*"
RASTERIZE = re.compile(
    CMD_POS + r"(?:pdftoppm|pdfimages|pdf2image)\b"
    r"|" + CMD_POS + r"pdftocairo\b[^\n;&|]*-(?:png|jpeg|jpg)\b"
    r"|" + CMD_POS + r"(?:convert|magick)\b[^\n;&|]*\.pdf\b",
    re.I,
)

HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?.*?^\1$", re.S | re.M)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif")

PROBE = ".claude/skills/tw-stock-research/scripts/pdf_chart_probe.py"


def deny(msg):
    sys.stderr.write(msg)
    sys.exit(2)  # exit 2 = 阻擋並把 stderr 回饋給模型


def main():
    try:
        ev = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # 讀不到事件就放行，不要因為 hook 自己壞掉卡住工作

    cwd = Path(ev.get("cwd") or ".")
    if (cwd / ".claude/.allow-image-read").exists():
        sys.exit(0)

    tool = ev.get("tool_name", "")
    inp = ev.get("tool_input") or {}

    if tool == "Bash":
        # heredoc 內容是資料不是指令（commit message、寫檔內容），先剔除再比對
        cmd = HEREDOC.sub("", str(inp.get("command", "")))
        if RASTERIZE.search(cmd):
            deny(
                "已阻擋：把 PDF 轉成圖檔。實測單頁 PNG 讀進 context 約 145,000 token，"
                "是 pdftotext 的 148 倍。\n"
                "若目的是核對圖表標籤（堆疊長條圖數字疊在一起、疑似重複），請改用：\n"
                f"  python3 {PROBE} <pdf> <page> -p '%$'\n"
                "它用 pdftotext -bbox-layout 的座標把標籤分群並對齊 X 軸，"
                "單頁輸出約 850 chars，且座標可稽核。分群太碎就加大 -t 容差重跑。\n"
                "若這頁確實是純圖片（pdftotext 抽不出任何文字），"
                "請先向使用者說明為什麼非轉不可，取得同意後 "
                "touch .claude/.allow-image-read 再執行，用完刪除。"
            )

    elif tool == "Read":
        fp = str(inp.get("file_path", ""))
        if fp.lower().endswith(IMAGE_EXT):
            deny(
                f"已阻擋：把圖檔讀進 context（{Path(fp).name}）。單張約 145,000 token。\n"
                "若這是從 PDF 轉出來要核對圖表的，請改用：\n"
                f"  python3 {PROBE} <pdf> <page> -p '%$'\n"
                "若是使用者自己提供、非看不可的圖，"
                "touch .claude/.allow-image-read 後重試，看完刪除。"
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
