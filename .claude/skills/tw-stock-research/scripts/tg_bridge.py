#!/usr/bin/env python3
"""把研究報告轉成 PDF 並發到 Telegram 頻道的本機橋接服務。

為什麼要有這個服務：報告裡的「匯出 PDF」是呼叫 window.print()，PDF 由瀏覽器
的列印對話框產生，網頁的 JS 拿不到那個檔案，所以沒辦法自己發出去。而 bot token
也絕對不能寫進報告 HTML（報告會被分享）。因此轉檔與發送都放在這支本機服務裡。

平常不必手動啟動：LaunchAgent（com.yen.twstock-tg）讓 launchd 守著 8787，報告頁按下
「發送到 TG」時才把這支程式叫起來，閒置 120 秒後自動退出，沒人用的時候是零進程。
安裝與管理方式見 references/telegram-sending.md。

手動用法：
  python3 tg_bridge.py                    啟動服務，然後用瀏覽器開 http://127.0.0.1:8787
  python3 tg_bridge.py --send <報告.html>  不開瀏覽器，直接把整份報告轉檔並發送
  python3 tg_bridge.py --port 9000 --reports /path/to/reports

裝了 LaunchAgent 之後 8787 由 launchd 佔著，不帶 --port 手動啟動會 bind 失敗；
--send 不開 port，不受影響。

設定檔 ~/.config/tw-stock-tg/config.json：
  {"bot_token": "123456:ABC...", "chat_id": "@your_channel"}
也可以改用環境變數 TW_STOCK_TG_BOT_TOKEN / TW_STOCK_TG_CHAT_ID。
"""

import argparse
import ctypes
import ctypes.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG_PATH = Path.home() / '.config' / 'tw-stock-tg' / 'config.json'
CHROME_CANDIDATES = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
]
TG_CAPTION_LIMIT = 1024      # Telegram 對 document caption 的上限
TG_FILE_LIMIT = 50 * 1024 * 1024   # bot sendDocument 的檔案上限


# ── 設定與環境 ────────────────────────────────────────────

def load_config():
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text('utf-8'))
        except (ValueError, OSError) as e:
            raise SystemExit('設定檔讀不到或格式錯誤：%s（%s）' % (CONFIG_PATH, e))
    token = os.environ.get('TW_STOCK_TG_BOT_TOKEN') or cfg.get('bot_token') or ''
    chat = os.environ.get('TW_STOCK_TG_CHAT_ID') or cfg.get('chat_id') or ''
    return token.strip(), str(chat).strip()


def find_chrome():
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    found = shutil.which('google-chrome') or shutil.which('chromium')
    if found:
        return found
    raise RuntimeError('找不到 Chrome／Chromium，無法轉 PDF')


def default_reports_dir():
    # scripts/ 在 .claude/skills/tw-stock-research/ 底下，往上四層是專案根目錄
    return Path(__file__).resolve().parents[4] / 'reports'


# ── HTML → PDF ───────────────────────────────────────────

def build_pdf(html_path: Path, out_pdf: Path, note='', off=None):
    """用 headless Chrome 把報告印成 PDF。

    筆記與章節勾選狀態平常存在瀏覽器的 localStorage，headless 用的是另一個
    profile、讀不到，所以改用注入 window.__TG_PRELOAD 的方式帶進去。
    """
    if out_pdf.exists():
        out_pdf.unlink()     # 輸出路徑是固定的，先清掉舊檔，免得轉檔失敗時把上一份誤判成新的
    preload = json.dumps({'note': note, 'off': off or []}, ensure_ascii=False)
    src = html_path.read_text('utf-8')
    inject = '<script>window.__TG_PRELOAD=%s;</script>' % preload
    if '</head>' in src:
        src = src.replace('</head>', inject + '</head>', 1)
    else:
        src = inject + src

    with tempfile.TemporaryDirectory() as td:
        staged = Path(td) / 'report.html'
        staged.write_text(src, 'utf-8')
        profile = Path(td) / 'chrome-profile'      # 用完即丟，不碰使用者平常那個 Chrome profile
        cmd = [
            find_chrome(),
            '--headless=new',
            '--disable-gpu',
            '--no-first-run',
            '--no-default-browser-check',
            '--user-data-dir=%s' % profile,
            # --incognito 是必要的：實測只帶 --user-data-dir 時 Chrome 印完 PDF 就掛住不退出
            # （檔案已寫好，行程要等到被 kill），加上 incognito 才會正常結束（約 3 秒）。
            '--incognito',
            '--no-pdf-header-footer',
            '--virtual-time-budget=15000',   # 等 Chart.js 把圖畫完
            '--print-to-pdf=%s' % out_pdf,
            staged.as_uri(),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    if not out_pdf.exists() or out_pdf.stat().st_size == 0:
        tail = (r.stderr or b'').decode('utf-8', 'replace')[-500:]
        raise RuntimeError('Chrome 轉 PDF 失敗：%s' % tail)
    return out_pdf


# ── Telegram Bot API ─────────────────────────────────────

def send_document(token, chat_id, pdf: Path, caption=''):
    size = pdf.stat().st_size
    if size > TG_FILE_LIMIT:
        raise RuntimeError('PDF %.1fMB 超過 Telegram bot 的 50MB 上限' % (size / 1048576))

    boundary = '----twstocktg' + uuid.uuid4().hex
    body = bytearray()

    def field(name, value):
        body.extend(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                     % (boundary, name, value)).encode('utf-8'))

    field('chat_id', chat_id)
    if caption:
        field('caption', caption[:TG_CAPTION_LIMIT])   # 純文字，不設 parse_mode，免得標題裡的符號被當標記
    body.extend(('--%s\r\nContent-Disposition: form-data; name="document"; filename="%s"\r\n'
                 'Content-Type: application/pdf\r\n\r\n' % (boundary, pdf.name)).encode('utf-8'))
    body.extend(pdf.read_bytes())
    body.extend(('\r\n--%s--\r\n' % boundary).encode('utf-8'))

    req = urllib.request.Request(
        'https://api.telegram.org/bot%s/sendDocument' % token,
        data=bytes(body),
        headers={'Content-Type': 'multipart/form-data; boundary=' + boundary},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            out = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:400]
        try:
            detail = json.loads(detail).get('description', detail)
        except ValueError:
            pass
        raise RuntimeError('Telegram 回應 %s：%s' % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError('連不到 Telegram：%s' % e.reason)
    if not out.get('ok'):
        raise RuntimeError('Telegram 拒絕：%s' % out.get('description'))
    return out['result']


# ── 共用流程 ─────────────────────────────────────────────

def convert_and_send(html_path: Path, token, chat_id, note='', off=None, caption=''):
    if not token or not chat_id:
        raise RuntimeError('還沒設定 bot_token / chat_id，請看 %s' % CONFIG_PATH)
    stem = re.sub(r'[\\/:*?"<>|]', '_', html_path.stem)
    pdf_dir = html_path.parent / 'pdf'       # reports/pdf/：PDF 留在本機，重發同一份會覆蓋
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdf_dir / (stem + '.pdf')
    build_pdf(html_path, pdf, note=note, off=off)
    result = send_document(token, chat_id, pdf, caption=caption)
    return {'ok': True, 'message_id': result.get('message_id'),
            'bytes': pdf.stat().st_size, 'pdf': str(pdf)}


# ── HTTP 服務 ────────────────────────────────────────────

INDEX_TMPL = """<!doctype html><meta charset="utf-8">
<title>台股研究報告</title>
<style>
body{font:15px/1.6 -apple-system,"Noto Sans TC",sans-serif;max-width:760px;margin:60px auto;padding:0 20px;color:#22251f}
h1{font-size:21px;margin:0 0 4px}p.h{color:#5A625D;font-size:13px;margin:0 0 28px}
a{display:block;padding:13px 16px;border:1px solid #E1E0D9;border-radius:8px;margin-bottom:8px;
  text-decoration:none;color:inherit}a:hover{border-color:#22251f}
.s{font:12px ui-monospace,monospace;color:#5A625D;margin-top:2px}
.warn{background:#fff6f5;border:1px solid #f3c9c4;border-radius:8px;padding:12px 16px;font-size:13px;margin-bottom:20px}
code{font:12px ui-monospace,monospace;background:#f2f1ec;padding:1px 5px;border-radius:3px}
</style>
<h1>台股研究報告</h1>
<p class="h">從這裡開啟報告，報告裡的「發送到 TG」按鈕才能用。</p>
%(status)s%(items)s
"""


class Handler(BaseHTTPRequestHandler):
    server_version = 'tw-stock-tg/1.0'

    def handle_one_request(self):
        # 讓閒置計時器知道現在有沒有請求在跑：轉 PDF 加上傳要 10–30 秒，
        # 這段期間不能被當成閒置而關掉。
        self.server.enter()
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        finally:
            self.server.leave()

    # 惡意網站的 JS 也能對 127.0.0.1 發 POST，所以要擋來源。
    # CORS 只能阻止對方讀回應，擋不住請求造成的副作用（真的發出去了）。
    def _origin_ok(self):
        origin = self.headers.get('Origin')
        if origin in (None, 'null'):     # 直接開檔（file://）或非瀏覽器的呼叫
            return True
        port = self.server.server_address[1]
        return origin in ('http://127.0.0.1:%d' % port, 'http://localhost:%d' % port)

    def _cors(self):
        origin = self.headers.get('Origin')
        self.send_header('Access-Control-Allow-Origin', origin if origin else '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def _json(self, code, payload):
        out = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _bytes(self, code, data, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _resolve_report(self, name):
        """只允許 reports 目錄底下的 .html，擋掉 ../ 這類路徑穿越。"""
        safe = Path(os.path.basename(name or ''))
        if safe.suffix.lower() not in ('.html', '.htm'):
            return None
        target = (self.server.reports_dir / safe).resolve()
        if target.parent != self.server.reports_dir.resolve() or not target.is_file():
            return None
        return target

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/':
            return self._bytes(200, self._index().encode('utf-8'), 'text/html; charset=utf-8')
        if path == '/api/status':
            token, chat = load_config()
            return self._json(200, {'configured': bool(token and chat), 'chat_id': chat})
        if path.startswith('/r/'):
            target = self._resolve_report(urllib.parse.unquote(path[3:]))
            if not target:
                return self._bytes(404, b'not found', 'text/plain')
            return self._bytes(200, target.read_bytes(), 'text/html; charset=utf-8')
        return self._bytes(404, b'not found', 'text/plain')

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != '/api/send':
            return self._json(404, {'ok': False, 'error': 'unknown endpoint'})
        if not self._origin_ok():
            return self._json(403, {'ok': False,
                                    'error': '拒絕來自 %s 的請求' % self.headers.get('Origin')})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        except (ValueError, UnicodeDecodeError) as e:
            return self._json(400, {'ok': False, 'error': 'body 解析失敗：%s' % e})

        target = self._resolve_report(req.get('file'))
        if not target:
            return self._json(400, {'ok': False,
                                    'error': '找不到報告檔 %r（只能發 reports 目錄裡的 .html）'
                                             % req.get('file')})
        token, chat = load_config()
        try:
            result = convert_and_send(
                target, token, chat,
                note=str(req.get('note') or ''),
                off=[str(x) for x in (req.get('off') or [])],
                caption=str(req.get('caption') or ''),
            )
        except Exception as e:
            self.log_line('發送失敗 %s：%s' % (target.name, e))
            return self._json(500, {'ok': False, 'error': str(e)})
        self.log_line('已發送 %s → %s（%.1fMB）｜PDF：%s'
                      % (target.name, chat, result['bytes'] / 1048576, result['pdf']))
        return self._json(200, result)

    def _index(self):
        token, chat = load_config()
        if token and chat:
            status = ''
        else:
            status = ('<div class="warn">尚未設定 Telegram：請在 <code>%s</code> 填入 '
                      '<code>bot_token</code> 與 <code>chat_id</code>，然後重新整理。</div>'
                      % CONFIG_PATH)
        files = sorted(self.server.reports_dir.glob('*.html'), reverse=True)
        if files:
            items = ''.join(
                '<a href="/r/%s">%s<div class="s">%.1f KB</div></a>'
                % (urllib.parse.quote(f.name), f.stem.replace('_', ' '), f.stat().st_size / 1024)
                for f in files)
        else:
            items = '<p class="h">%s 裡還沒有報告。</p>' % self.server.reports_dir
        return INDEX_TMPL % {'status': status, 'items': items}

    def log_line(self, msg):
        sys.stderr.write('  %s\n' % msg)
        sys.stderr.flush()

    def log_message(self, fmt, *args):
        pass     # 預設的 access log 太吵，只留我們自己的訊息


class BridgeServer(ThreadingHTTPServer):
    """多記兩件事：有幾個請求正在處理、上一個請求何時結束——閒置計時器要用。"""

    def __init__(self, *a, **kw):
        ThreadingHTTPServer.__init__(self, *a, **kw)
        self._inflight = 0
        self._since = time.time()
        self._lock = threading.Lock()

    def enter(self):
        with self._lock:
            self._inflight += 1

    def leave(self):
        with self._lock:
            self._inflight -= 1
            self._since = time.time()

    def idle_seconds(self):
        with self._lock:
            return 0 if self._inflight else time.time() - self._since


def launchd_socket(name='Listeners'):
    """接手 launchd 已經開好並綁定的 listening socket。

    launchd 平常只是守著 port、不跑任何進程；第一個連線進來才把這支程式叫起來，
    再用這個 API 把綁好的 socket 交過來。閒置後我們自己退出，launchd 繼續守著，
    所以「沒人用的時候零進程、要用的時候自動起來」。
    """
    lib = ctypes.CDLL(ctypes.util.find_library('System'), use_errno=True)
    fn = lib.launch_activate_socket
    fn.argtypes = [ctypes.c_char_p,
                   ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
                   ctypes.POINTER(ctypes.c_size_t)]
    fn.restype = ctypes.c_int
    fds = ctypes.POINTER(ctypes.c_int)()
    cnt = ctypes.c_size_t(0)
    rc = fn(name.encode(), ctypes.byref(fds), ctypes.byref(cnt))
    if rc != 0 or cnt.value < 1:
        raise SystemExit('拿不到 launchd 的 socket（rc=%d）：--launchd 只能由 launchd 啟動，'
                         '不要自己在終端機跑' % rc)
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM, fileno=fds[0])


def serve(port, reports_dir, use_launchd=False, idle=0):
    if use_launchd:
        sock = launchd_socket()
        httpd = BridgeServer(('127.0.0.1', 0), Handler, bind_and_activate=False)
        httpd.socket = sock
        # 跳過 server_bind 就得自己補這幾個欄位（_origin_ok 會讀 port）
        httpd.server_address = sock.getsockname()
        httpd.server_name = socket.getfqdn(httpd.server_address[0])
        httpd.server_port = port = httpd.server_address[1]
    else:
        httpd = BridgeServer(('127.0.0.1', port), Handler)
    httpd.reports_dir = reports_dir

    token, chat = load_config()
    if use_launchd:
        # 這些訊息會進 launchd 的 log 檔，寫成單行方便對時間
        sys.stderr.write('%s 由 launchd 喚醒（port %d，閒置 %d 秒後自動退出）\n'
                         % (time.strftime('%H:%M:%S'), port, idle))
        sys.stderr.flush()
    else:
        print('報告目錄：%s' % reports_dir)
        print('Telegram：%s' % ('已設定 → %s' % chat if token and chat
                                else '尚未設定（請填 %s）' % CONFIG_PATH))
        print('\n  用瀏覽器開 http://127.0.0.1:%d  （Ctrl-C 結束）\n' % port)

    if idle > 0:
        def watchdog():
            while httpd.idle_seconds() <= idle:
                time.sleep(5)
            httpd.shutdown()      # 讓 serve_forever() 收工，進程正常結束
        threading.Thread(target=watchdog, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
        return
    if use_launchd:
        sys.stderr.write('%s 閒置滿 %d 秒，退出\n' % (time.strftime('%H:%M:%S'), idle))
        sys.stderr.flush()


def main():
    ap = argparse.ArgumentParser(description='把台股研究報告轉 PDF 並發到 Telegram')
    ap.add_argument('--port', type=int, default=8787)
    ap.add_argument('--reports', type=Path, default=None, help='報告目錄')
    ap.add_argument('--send', type=Path, default=None, help='直接發送這份報告（整份、不含筆記）')
    ap.add_argument('--launchd', action='store_true',
                    help='接手 launchd 交來的 socket（由 LaunchAgent 啟動，不要手動用）')
    ap.add_argument('--idle', type=int, default=0,
                    help='閒置這麼多秒後自動退出；0 表示不自動退出')
    args = ap.parse_args()

    reports_dir = (args.reports or default_reports_dir()).resolve()
    if args.send:
        token, chat = load_config()
        html = args.send.resolve()
        if not html.is_file():
            raise SystemExit('找不到檔案：%s' % html)
        print('轉檔中：%s' % html.name)
        result = convert_and_send(html, token, chat, caption=html.stem.replace('_', ' '))
        print('已發送到 %s（message_id=%s, %.1fMB）'
              % (chat, result['message_id'], result['bytes'] / 1048576))
        print('PDF 留在 %s' % result['pdf'])
        return
    if not reports_dir.is_dir():
        raise SystemExit('報告目錄不存在：%s（用 --reports 指定）' % reports_dir)
    serve(args.port, reports_dir, use_launchd=args.launchd, idle=args.idle)


if __name__ == '__main__':
    main()
