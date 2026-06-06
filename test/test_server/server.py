import http.server
import time
import os
import threading
import sys

# 全域計數器與鎖，用以安全記錄請求次數
request_counter = {
    '/temporary-error': 0
}
counter_lock = threading.Lock()

class MockHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    自訂 Mock HTTP 伺服器，模擬爬蟲在真實環境中會遭遇的各種複雜情境。
    """
    
    def log_message(self, format, *args):
        # 覆寫日誌輸出，讓終端機保持整潔，不干擾爬蟲 CLI 輸出
        sys.stderr.write(f"MockServer - - [{self.log_date_time_string()}] {format % args}\n")

    def do_GET(self):
        # 1. 測試：指數退避重試（前 2 次返回 503 暫時性錯誤，第 3 次返回 200）
        if self.path == '/temporary-error':
            with counter_lock:
                request_counter['/temporary-error'] += 1
                current_count = request_counter['/temporary-error']
            
            if current_count <= 2:
                self.send_response(503)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"503 Service Unavailable (Temporary Error for Testing)")
            else:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Success! Retry worked.</h1></body></html>")
            return

        # 2. 測試：網路超時 (Slow Response)
        if self.path == '/slow-response':
            time.sleep(15)  # 阻礙 15 秒以觸發爬蟲的 timeout (預設 10 秒)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Slow response completed</h1></body></html>")
            return

        # 3. 測試：302 重新導向 (Redirect)
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/subfolder/target.html')
            self.end_headers()
            return

        # 4. 測試：MIME-Type 攔截與 Stream 中斷 (Infinite binary stream)
        if self.path == '/infinite-stream':
            self.send_response(200)
            # 故意宣告非 HTML 類型，驗證爬蟲是否一讀取到 Header 就立刻 Abort，而不會下載完整資料
            self.send_header('Content-Type', 'application/octet-stream')
            self.end_headers()
            try:
                # 若連線沒被爬蟲中斷，會一直寫入二進位數據
                for _ in range(100):
                    self.wfile.write(b"0" * 1024)
                    time.sleep(0.1)
            except Exception:
                # 預期會因為爬蟲主動 Close 連線而拋出 BrokenPipeError
                pass
            return

        # 5. 測試：User-Agent 阻擋與驗證
        if self.path == '/protected-area':
            ua = self.headers.get('User-Agent', '')
            # 若 UA 不含 Chrome 或 Mozilla，回傳 403 代表非偽裝瀏覽器
            if 'Chrome' in ua or 'Mozilla' in ua:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Access Granted to Browser User-Agent</h1></body></html>")
            else:
                self.send_response(403)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"403 Forbidden - Only web browsers are allowed!")
            return

        # 6. 靜態檔案回傳（index.html, page2.html, 以及重新導向後的 subfolder 目錄內容）
        # 移除前面的斜線，以便在本地目錄尋找
        local_path = self.path.lstrip('/')
        if local_path == '':
            local_path = 'index.html'

        # 基礎路徑安全性防護，避免 Path Traversal 讀取專案外檔案
        base_dir = os.path.abspath(os.path.dirname(__file__))
        target_abs_path = os.path.abspath(os.path.join(base_dir, local_path))
        if not target_abs_path.startswith(base_dir):
            self.send_response(403)
            self.end_headers()
            return

        if os.path.exists(target_abs_path) and os.path.isfile(target_abs_path):
            self.send_response(200)
            if local_path.endswith('.html'):
                self.send_header('Content-Type', 'text/html; charset=utf-8')
            elif local_path.endswith('.pdf'):
                self.send_header('Content-Type', 'application/pdf')
            else:
                self.send_header('Content-Type', 'application/octet-stream')
            self.end_headers()
            with open(target_abs_path, 'rb') as f:
                self.wfile.write(f.read())
            return

        # 檔案不存在，返回 404
        self.send_response(404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"404 Not Found")

def run(port=8000):
    server_address = ('', port)
    httpd = http.server.HTTPServer(server_address, MockHTTPRequestHandler)
    sys.stderr.write(f"Starting Mock Server on port {port}...\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nStopping Mock Server...\n")
        httpd.server_close()

if __name__ == '__main__':
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run(port=port)
