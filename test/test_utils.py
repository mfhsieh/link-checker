"""
針對 crawler.utils 模組工具函式之單元測試。

測試重點：
- sanitize_error_message 的敏感資料過濾 (IPv4, IPv6, Credentials, Header Tokens)
- sanitize_error_message 的 Log Injection (CRLF) 換行符清洗
- 邊界情況 (None, 空字串, 無敏感資訊之正常文字)
"""

from crawler.utils import sanitize_error_message


class TestSanitizeErrorMessage:
    """測試 sanitize_error_message 敏感訊息與 log 注入防禦。"""

    def test_empty_and_none_input(self) -> None:
        """驗證 None 與空字串回傳空字串。"""
        assert sanitize_error_message(None) == ""
        assert sanitize_error_message("") == ""

    def test_normal_message_unchanged(self) -> None:
        """驗證一般不含敏感資訊的訊息維持不變。"""
        msg = "HTTP 404 Not Found at path /index.html"
        assert sanitize_error_message(msg) == msg

    def test_url_credentials_masking(self) -> None:
        """驗證 URL 內的帳號密碼會被遮蔽。"""
        raw = "Connect to http://admin:secret123@example.com/api failed"
        expected = "Connect to http://***:***@example.com/api failed"
        assert sanitize_error_message(raw) == expected

        raw_https = "Connect to https://user_name:p%40ssword@sub.domain.org/path failed"
        expected_https = "Connect to https://***:***@sub.domain.org/path failed"
        assert sanitize_error_message(raw_https) == expected_https

    def test_sensitive_headers_masking(self) -> None:
        """驗證 Cookie, Authorization, Bearer 標頭會被遮蔽。"""
        raw_cookie = "Header Set-Cookie: session_id=xyz123456"
        assert "***" in sanitize_error_message(raw_cookie)
        assert "xyz123456" not in sanitize_error_message(raw_cookie)

        raw_auth = "Authorization: secret_jwt_token_here"
        sanitized = sanitize_error_message(raw_auth)
        assert "secret_jwt_token_here" not in sanitized

        raw_bearer = "Bearer: my_secret_token"
        sanitized_bearer = sanitize_error_message(raw_bearer)
        assert "my_secret_token" not in sanitized_bearer

    def test_ipv4_masking(self) -> None:
        """驗證 IPv4 地址遮蔽。"""
        raw = "Failed to connect to 192.168.1.100 port 8080"
        expected = "Failed to connect to [IP_MASKED] port 8080"
        assert sanitize_error_message(raw) == expected

    def test_ipv6_masking(self) -> None:
        """驗證包含完整與 :: 縮寫格式的 IPv6 地址遮蔽。"""
        # 完整 IPv6
        raw_full = "Error connecting to 2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        assert "[IP_MASKED]" in sanitize_error_message(raw_full)

        # 縮寫 IPv6
        raw_short = "Connection refused by ::1"
        assert "[IP_MASKED]" in sanitize_error_message(raw_short)

        raw_ula = "Target fd00::1 unreachable"
        assert "[IP_MASKED]" in sanitize_error_message(raw_ula)

    def test_log_injection_crlf_stripping(self) -> None:
        """驗證 CRLF (\\r, \\n) 換行符會被替換/清洗以防止 Log Injection。"""
        raw = "Error 500\r\n[CRITICAL] Fake Log Entry Injected\nNext line"
        sanitized = sanitize_error_message(raw)
        assert "\r" not in sanitized
        assert "\n" not in sanitized
        assert "[CRITICAL] Fake Log Entry Injected" in sanitized
