"""
這是一個獨立的網址跳轉追蹤工具。

利用 httpx 與 BeautifulSoup 來追蹤給定網址的 HTTP 重導向與 HTML Meta Refresh 客戶端跳轉歷程。
"""

import re
import sys
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup


def trace_url(start_url: str) -> None:
    """
    追蹤並印出網址的完整跳轉歷程。

    支援伺服器端 HTTP 3xx 跳轉與客戶端 HTML Meta Refresh 跳轉。
    遇到無窮迴圈或連線錯誤時會中斷並印出警告。

    Args:
        start_url (str): 欲追蹤的起始網址。

    Returns:
        None
    """
    print(f"開始追蹤跳轉歷程: {start_url}")
    print("-" * 40)

    headers: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    current_url: str = start_url
    visited: set[str] = set()

    # 這裡使用 httpx，它會自動處理 Cookie 跨網域保持 (預設啟動 Cookie 引擎)
    with httpx.Client(verify=False) as client:
        while current_url:
            if current_url in visited:
                print(f"[警告] 偵測到無窮迴圈跳轉: {current_url}")
                break
            visited.add(current_url)

            try:
                # 關閉自動跳轉，我們手動逐步解析以印出完整歷程
                response = client.get(current_url, headers=headers, follow_redirects=False, timeout=10.0)

                print(f"HTTP/{response.http_version} {response.status_code}")
                # 印出關鍵標頭
                for k, v in response.headers.items():
                    if k.lower() in ["location", "set-cookie"]:
                        print(f"{k.title()}: {v}")

                # 1. 處理伺服器端重導向 (HTTP 3xx)
                if response.is_redirect and "location" in response.headers:
                    next_url: str = urljoin(current_url, response.headers["location"])
                    print(f"-> [伺服器重導向] 至: {next_url}\n")
                    current_url = next_url
                    continue

                # 2. 處理客戶端重導向 (<meta http-equiv="refresh">)
                if response.status_code == 200 and "text/html" in response.headers.get("content-type", "").lower():
                    soup = BeautifulSoup(response.text, "html.parser")
                    meta_refresh = soup.find("meta", attrs={"http-equiv": lambda x: x and x.lower() == "refresh"})
                    if meta_refresh:
                        content: str = str(meta_refresh.get("content", ""))
                        match = re.search(r"url\s*=\s*['\"]?([^'\"]+)", content, re.IGNORECASE)
                        if match:
                            meta_url: str = match.group(1).strip()
                            next_url = urljoin(current_url, meta_url)
                            print(f"-> [Meta Refresh 客戶端跳轉] 偵測到，將前往: {next_url}\n")
                            current_url = next_url
                            continue

                # 若無任何跳轉，則視為最終落點
                print(f"\n[Final URL]: {current_url}")
                break

            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"\n[錯誤] 連線失敗: {e}")
                break
    print("-" * 40)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <URL>")
        sys.exit(1)
    trace_url(sys.argv[1])
