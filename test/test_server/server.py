"""
Mock HTTP 伺服器模組。

此模組提供了一個自訂的 HTTP 伺服器，用來模擬各種網路連線情境（重定向、暫時性錯誤、超時等），
以供端到端 (E2E) 與單元測試使用。
"""

import http.server
import time
import os
import threading
import sys

# 全域計數器與鎖，用以安全記錄請求次數
request_counter: dict[str, int] = {"/temporary-error": 0, "/flaky_internal": 0}
counter_lock: threading.Lock = threading.Lock()


class MockHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    自訂 Mock HTTP 伺服器，模擬爬蟲在真實環境中會遭遇的各種複雜情境。
    """

    # pylint: disable=arguments-differ, redefined-builtin
    def log_message(self, format: str, *args: object) -> None:
        """
        覆寫日誌輸出，改以特定的 MockServer 前綴輸出至 stderr，保持終端機整潔。

        Args:
            format (str): 日誌格式化字串。
            *args (object): 要填入格式化字串的變數。
        """
        sys.stderr.write(f"MockServer - - [{self.log_date_time_string()}] {format % args}\n")

    # pylint: disable=invalid-name,too-many-return-statements
    # pylint: disable=too-many-branches,too-many-statements
    def do_GET(self) -> None:
        """
        處理所有的 HTTP GET 請求，模擬指數退避重試、網路超時、重定向、特定 MIME 類型等多種情境。
        """
        # 1. 測試：指數退避重試（前 2 次返回 503 暫時性錯誤，第 3 次返回 200）
        if self.path == "/temporary-error":
            with counter_lock:
                request_counter["/temporary-error"] += 1
                current_count: int = request_counter["/temporary-error"]

            if current_count <= 2:
                self.send_response(503)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"503 Service Unavailable (Temporary Error for Testing)")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Success! Retry worked.</h1></body></html>")
            return

        # 2. 測試：網路超時 (Slow Response)
        if self.path == "/slow-response":
            time.sleep(15)  # 阻礙 15 秒以觸發爬蟲的 timeout (預設 10 秒)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Slow response completed</h1></body></html>")
            return

        # 3. 測試：302 重新導向 (Redirect)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/subfolder/target.html")
            self.end_headers()
            return

        # 4. 測試：MIME-Type 攔截與 Stream 中斷 (Infinite binary stream)
        if self.path == "/infinite-stream":
            self.send_response(200)
            # 故意宣告非 HTML 類型，驗證爬蟲是否一讀取到 Header 就立刻 Abort，而不會下載完整資料
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            try:
                # 若連線沒被爬蟲中斷，會一直寫入二進位數據
                for _ in range(100):
                    self.wfile.write(b"0" * 1024)
                    time.sleep(0.1)
            except Exception:  # pylint: disable=broad-exception-caught
                # 預期會因為爬蟲主動 Close 連線而拋出 BrokenPipeError
                pass
            return

        # 5. 測試：User-Agent 阻擋與驗證
        if self.path == "/protected-area":
            ua = self.headers.get("User-Agent", "")
            # 若 UA 不含 Chrome 或 Mozilla，回傳 403 代表非偽裝瀏覽器
            if "Chrome" in ua or "Mozilla" in ua:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Access Granted to Browser User-Agent</h1></body></html>")
            else:
                self.send_response(403)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"403 Forbidden - Only web browsers are allowed!")
            return

        # 7. 測試：失敗重試 (Flaky Endpoint)
        if self.path == "/flaky_internal":
            with counter_lock:
                request_counter["/flaky_internal"] = request_counter.get("/flaky_internal", 0) + 1
                current_count: int = request_counter["/flaky_internal"]

            if current_count <= 1:
                self.send_response(500)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"500 Internal Server Error (Flaky)")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Flaky Page Recovered!</h1>"
                    b"<a href='https://www.example.com'>Example</a></body></html>"
                )
            return

        # 8. 測試：重置 Flaky 狀態
        if self.path == "/reset_flaky":
            with counter_lock:
                request_counter["/flaky_internal"] = 0
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"message": "State reset"}')
            return

        # 9. 測試：Tarpit 端點 (Timeout Simulation)
        if self.path == "/tarpit":
            time.sleep(10)  # 阻礙 10 秒以觸發進階測試的 external_check_timeout (2.0s)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>Too late!</body></html>")
            return

        # 10. 測試：Advanced Test 進入點
        if self.path == "/advanced_test":
            port = self.server.server_address[1]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body>"
                b"<a href='/flaky_internal'>Flaky Internal</a> "
                + f"<a href='http://localhost:{port}/tarpit'>Tarpit External</a>".encode("utf-8")
                + b"</body></html>"
            )
            return

        # 6. 靜態檔案回傳（index.html, page2.html, 以及重新導向後的 subfolder 目錄內容）
        # 先分離 query string 與 path
        path_without_query: str = self.path.split("?")[0]

        # 移除前面的斜線，以便在本地目錄尋找
        local_path: str = path_without_query.lstrip("/")
        if local_path == "":
            local_path = "index.html"

        # 基礎路徑安全性防護，避免 Path Traversal 讀取專案外檔案
        base_dir = os.path.abspath(os.path.dirname(__file__))
        target_abs_path = os.path.abspath(os.path.join(base_dir, local_path))
        if not target_abs_path.startswith(base_dir):
            self.send_response(403)
            self.end_headers()
            return

        if os.path.exists(target_abs_path) and os.path.isfile(target_abs_path):
            self.send_response(200)
            if local_path.endswith(".html"):
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(target_abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                port = self.server.server_address[1]
                content = content.replace("127.0.0.1", f"127.0.0.1:{port}")
                content = content.replace("localhost", f"localhost:{port}")
                self.wfile.write(content.encode("utf-8"))
                return
            elif local_path.endswith(".pdf"):
                self.send_header("Content-Type", "application/pdf")
            else:
                self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            with open(target_abs_path, "rb") as f:
                self.wfile.write(f.read())
            return

        # 檔案不存在，返回 404
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def do_HEAD(self) -> None:
        """
        處理 HTTP HEAD 請求。
        模擬 Tarpit 超時，其餘路徑回傳 501 以符合 mock-social-media 測試期待。
        """
        if self.path == "/tarpit":
            time.sleep(10)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return

        self.send_error(501, "Unsupported method ('HEAD')")


def run(port: int = 8000) -> None:
    """
    啟動並執行 Mock HTTP 伺服器本體。

    Args:
        port (int): 伺服器監聽的 TCP 通訊埠，預設為 8000。
    """
    server_address = ("", port)
    httpd = http.server.HTTPServer(server_address, MockHTTPRequestHandler)
    sys.stderr.write(f"Starting Mock Server on port {port}...\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nStopping Mock Server...\n")
        httpd.server_close()


if __name__ == "__main__":
    server_port: int = 8000
    if len(sys.argv) > 1:
        try:
            server_port = int(sys.argv[1])
        except ValueError:
            pass
    run(port=server_port)
