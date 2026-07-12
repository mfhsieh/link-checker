# pylint: disable=cyclic-import
"""
Mock HTTP 伺服器模組。

此模組提供了一個自訂的 HTTP 伺服器，用來模擬各種網路連線情境（重定向、暫時性錯誤、超時等），
以供端到端 (E2E) 與單元測試使用。
"""

import http.server
import os
import sys
import threading
import time
from typing import cast

# 全域計數器與鎖，用以安全記錄請求次數
request_counter: dict[str, int] = {"/temporary-error": 0, "/flaky_internal": 0}
counter_lock: threading.Lock = threading.Lock()


class MockHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    自訂 Mock HTTP 請求處理器。

    此處理器繼承自 `http.server.BaseHTTPRequestHandler`，專為測試環境設計，
    用以模擬爬蟲在真實網路環境中可能遭遇的各種複雜情境，包含暫時性服務中斷 (503)、
    回應緩慢、重定向、特定的 MIME-Type 攔截、User-Agent 驗證以及社群網域模擬等。
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
        處理 HTTP GET 請求，模擬多種網路邊際案例。

        根據請求路徑 (path) 執行不同的模擬邏輯：
        - `/temporary-error`: 模擬前兩次失敗 (503)，第三次成功的指數退避情境。
        - `/slow-response`: 模擬回應延遲（阻塞 1 秒）。
        - `/redirect`: 執行 302 重新導向至特定子目錄。
        - `/infinite-stream`: 模擬無限二進位流以測試爬蟲的 MIME 攔截機制。
        - `/protected-area`: 驗證 User-Agent 是否符合瀏覽器特徵。
        - `/flaky_internal`: 模擬具備失敗重試特性的內部頁面。
        - `/tarpit`: 模擬極慢連線以觸發連線逾時設定。
        - 其他路徑則嘗試搜尋並回傳對應的本地靜態檔案 (HTML, PDF 等)。

        Returns:
            None
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
            time.sleep(1)  # 阻礙 1 秒 (原 15 秒，避免測試過久，且在 timeout=2 內完成)
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
            except (BrokenPipeError, ConnectionResetError):
                # 預期會因為爬蟲主動 Close 連線而拋出 BrokenPipeError 等連線中斷例外
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
                current_count = request_counter["/flaky_internal"]

            if current_count <= 2:
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
            time.sleep(2)  # 阻礙 2 秒以觸發進階測試的 external_check_timeout
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>Too late!</body></html>")
            return

        # 10. 測試：Advanced Test 進入點
        if self.path == "/advanced_test":
            port = cast(tuple[str, int], self.server.server_address)[1]
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

        # 11. 測試：社群網域與非社群網域的 GET 降級
        if self.path in ("/mock-social-media", "/mock-non-social"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Mock Media</h1></body></html>")
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
                port = cast(tuple[str, int], self.server.server_address)[1]
                content = content.replace("127.0.0.1", f"127.0.0.1:{port}")
                content = content.replace("127.0.0.2", f"127.0.0.2:{port}")
                content = content.replace("localhost", f"localhost:{port}")
                self.wfile.write(content.encode("utf-8"))
                return
            if local_path.endswith(".pdf"):
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

        主要用於模擬針對社群網域或特定端點的探測行為。針對 `/tarpit` 會模擬延遲，
        而針對 `/mock-social-media` 等路徑則會回傳 520 錯誤以模擬特定 WAF 行為。

        Returns:
            None
        """
        if self.path == "/tarpit":
            time.sleep(2)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return

        if self.path in ("/mock-social-media", "/mock-non-social"):
            self.send_error(520, "Unknown Error (WAF Mock)")
            return

        self.send_error(501, "Unsupported method ('HEAD')")


def run(port: int = 8000) -> None:
    """
    啟動並執行 Mock HTTP 伺服器本體。

    Args:
        port (int): 伺服器監聽的 TCP 通訊埠，預設為 8000。
    """
    server_address = ("", port)
    httpd = http.server.ThreadingHTTPServer(server_address, MockHTTPRequestHandler)
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
