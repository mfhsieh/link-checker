#!/bin/bash
# 遇到任何一個測試失敗就立刻中斷
set -e

# 切換到專案根目錄 (確保腳本從任何位置執行都能正確找到測試路徑)
cd "$(dirname "$0")/.."

echo "=== 執行 E2E 測試 ==="
pytest test/e2e/ -v

echo "=== 執行後台日誌測試 ==="
pytest test/test_admin_logs.py -v

echo "=== 執行 API 整合測試 ==="
pytest test/test_api.py -v

echo "=== 執行 CLI 整合測試 ==="
pytest test/test_cli.py -v
