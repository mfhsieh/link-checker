"""
被忽略內部連結之輕量死檔探測功能的單元測試模組。

驗證當啟用或停用 check_skipped_links 設定時，符合忽略副檔名與排除路徑規則的
內部連結在 core.py 抓取過程中的行為與回傳狀態。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from crawler.core import CrawlerCore
from crawler.models import CrawlerConfig


def test_skipped_links_probing_success() -> None:
    """
    測試符合忽略規則的內部資源存在時 (200 OK) 的探測情形。

    驗證當啟用 `check_skipped_links` 且內部連結符合略過副檔名規則，且該連結伺服器回傳
    200 OK 狀態時：
    1. 爬蟲核心會正確發出 GET 串流探測 (stream)。
    2. 回傳狀態碼應為 200。
    3. 最終爬取狀態應為 'skip' (表示探測成功後略過解析)。
    4. 回傳錯誤訊息應標明為忽略原因。
    """
    config = CrawlerConfig(ignore_extensions=[".pdf"], check_skipped_links=True)
    crawler = CrawlerCore(config=config)

    # 模擬 httpx 回應標頭
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "application/pdf"}

    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_response

    # 模擬 client.stream 串流被呼叫且在標頭讀取後立即關閉
    with patch.object(crawler.client, "stream", return_value=mock_context) as mock_stream:
        res = crawler.fetch("https://example.com/document.pdf", target_domains=["example.com"])
        # 回傳格式為 (text_or_redirects, status_code, status, url, request_sent, err_msg)
        assert res[1] == 200
        assert res[2] == "skip"
        assert res[5] == "符合忽略之副檔名"
        mock_stream.assert_called_once()

    crawler.close()


def test_skipped_links_probing_failure() -> None:
    """
    測試符合忽略規則的內部資源不存在時 (404 Not Found) 的探測情形。

    驗證當啟用 `check_skipped_links` 且內部連結符合略過副檔名規則，但該連結伺服器回傳
    404 Not Found 錯誤時：
    1. 爬蟲核心會發出 GET 串流探測並觸發 raise_for_status 例外。
    2. 回傳狀態碼應為 404。
    3. 最終爬取狀態應為 'failed' (表示確認為死鏈)。
    4. 錯誤訊息中應包含 404 狀態說明。
    """
    config = CrawlerConfig(ignore_extensions=[".pdf"], check_skipped_links=True)
    crawler = CrawlerCore(config=config)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=MagicMock(), response=mock_response
    )

    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_response

    with patch.object(crawler.client, "stream", return_value=mock_context) as mock_stream:
        res = crawler.fetch("https://example.com/document.pdf", target_domains=["example.com"])
        assert res[1] == 404
        assert res[2] == "failed"
        assert res[5] is not None and "404" in res[5]
        mock_stream.assert_called_once()

    crawler.close()


def test_skipped_links_probing_disabled() -> None:
    """
    測試當停用 check_skipped_links 設定時的爬取情形。

    驗證當停用 `check_skipped_links` (例如針對歷史舊任務或關閉探測) 且連結符合忽略規則時：
    1. 爬蟲核心不應該對該連結發起任何網路請求 (stream)。
    2. 回傳狀態碼應為 None。
    3. 最終爬取狀態應直接標記為 'skip'。
    4. 回傳錯誤訊息應標明為忽略原因。
    """
    config = CrawlerConfig(ignore_extensions=[".pdf"], check_skipped_links=False)
    crawler = CrawlerCore(config=config)

    with patch.object(crawler.client, "stream") as mock_stream:
        res = crawler.fetch("https://example.com/document.pdf", target_domains=["example.com"])
        assert res[1] is None
        assert res[2] == "skip"
        assert res[5] == "符合忽略之副檔名"
        mock_stream.assert_not_called()

    crawler.close()
