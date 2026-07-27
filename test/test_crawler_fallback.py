"""
針對 CrawlerCore.check_external_link 核心降級路徑之專屬單元與整合測試套件。

測試重點涵蓋：
1. HEAD 請求遭遇 RequestError (如 Tarpit / 逾時 / 網路連線切斷) 成功降級為 GET 請求探測。
2. HEAD 請求回傳 3xx 重導向、404/405 等狀態碼或社群網域時，成功降級為 GET 探測。
3. 明文 HTTP 探測失敗時，自動嘗試升級至 HTTPS 重新探測。
4. 遭遇 WAF 阻擋狀態碼 (如 403, 520) 時，成功觸發 curl_cffi TLS 偽裝降級備援引擎。
5. 重導向過程中 Set-Cookie 的跨跳分桶與繼承傳輸機制。
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from crawler.core import CrawlerCore
from crawler.models import CrawlerConfig


class TestCrawlerCoreFallbackPaths:
    """測試 CrawlerCore.check_external_link 的多層降級機制。"""

    @pytest.fixture
    def core(self) -> CrawlerCore:
        """建立 CrawlerCore 測試實例。"""
        config = CrawlerConfig(
            external_check_timeout=2.0,
            max_redirects=3,
            social_domains=["facebook.com", "instagram.com"],
        )
        return CrawlerCore(config)

    def test_head_request_error_fallback_to_get(self, core: CrawlerCore) -> None:
        """驗證 HEAD 請求發生網路層異常時，會自動降級使用 GET 請求探測並成功返回。"""
        url = "https://example.com/test-head-fallback"

        def mock_request(method: str, *args, **kwargs):
            del args, kwargs  # 未使用的參數
            if method == "HEAD":
                raise httpx.ConnectTimeout("HEAD timeout simulation")
            if method == "GET":
                # 回傳模擬的 stream response
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.headers = {"Content-Type": "text/html"}
                mock_resp.cookies.jar = []
                # mock stream context manager
                cm = MagicMock()
                cm.__enter__.return_value = mock_resp
                return cm
            raise ValueError(f"Unexpected method {method}")

        with (
            patch.object(core.client, "request", side_effect=mock_request),
            patch.object(core.client, "stream", side_effect=mock_request),
        ):
            status_code, err_msg = core.check_external_link(url)
            assert status_code == 200
            assert err_msg is None

    def test_head_status_404_fallback_to_get(self, core: CrawlerCore) -> None:
        """驗證 HEAD 請求回傳 404 等易誤判狀態碼時，降級為 GET 進行二次確認。"""
        url = "https://example.com/maybe-404"

        head_resp = MagicMock()
        head_resp.status_code = 404

        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.headers = {}
        get_resp.cookies.jar = []
        get_cm = MagicMock()
        get_cm.__enter__.return_value = get_resp

        with (
            patch.object(core.client, "request", return_value=head_resp),
            patch.object(core.client, "stream", return_value=get_cm),
        ):
            status_code, err_msg = core.check_external_link(url)
            assert status_code == 200
            assert err_msg is None

    def test_http_failure_upgrades_to_https(self, core: CrawlerCore) -> None:
        """驗證明文 HTTP 探測失敗 (例如連線拒絕) 時，自動嘗試升級至 HTTPS 並取得結果。"""
        http_url = "http://secure-only-site.com"

        def mock_check_single(url: str, *args, **kwargs):
            del args, kwargs
            if url == http_url:
                # HTTP 失敗
                return None, (None, "httpx.ConnectError: Connection refused")
            if url == "https://secure-only-site.com":
                # HTTPS 成功
                return None, (200, None)
            return None, (None, "Unknown")

        with patch.object(core, "_check_external_single", side_effect=mock_check_single):
            status_code, err_msg = core.check_external_link(http_url)
            assert status_code == 200
            assert err_msg is None

    def test_waf_403_triggers_tls_impersonate_fallback(self, core: CrawlerCore) -> None:
        """驗證當請求遭 WAF 回傳 403 阻擋時，觸發 curl_cffi TLS 偽裝降級。"""
        url = "https://protected-by-waf.com"

        waf_result = (None, (403, "Forbidden by WAF"))

        with (
            patch.object(core, "_check_external_single", return_value=waf_result),
            patch.object(core, "_execute_curl_cffi_fallback", return_value=(200, None, "OK", url)) as mock_cffi,
        ):
            status_code, err_msg = core.check_external_link(url)
            assert status_code == 200
            assert err_msg is None
            mock_cffi.assert_called_once_with(url, is_internal=False)

    def test_cookie_aggregation_across_redirects(self, core: CrawlerCore) -> None:
        """驗證重導向時的分桶 Cookie 收集與繼承邏輯。"""
        accumulated: dict[str, dict[str, str]] = {}

        # 測試 _get_applicable_cookies
        accumulated[".example.com"] = {"session_id": "abc123"}
        accumulated["sub.example.com"] = {"token": "xyz789"}

        cookies_sub = core._get_applicable_cookies("sub.example.com", accumulated)  # pylint: disable=protected-access
        assert cookies_sub["session_id"] == "abc123"
        assert cookies_sub["token"] == "xyz789"

        cookies_other = core._get_applicable_cookies("other.com", accumulated)  # pylint: disable=protected-access
        assert cookies_other == {}
