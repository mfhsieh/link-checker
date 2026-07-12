#!/bin/bash
# 開啟 Fail-Fast 機制：只要有任何一行指令報錯 (非 0 退出碼)，腳本就會立刻中斷
set -e 

# 進入專案根目錄 (確保腳本可以在任何地方被呼叫)
cd "$(dirname "$0")/../../../.."

# 確保載入虛擬環境
source .venv/bin/activate

echo "========================================"
echo "[1/4] 執行自動排版與匯入排序 (Ruff)..."
echo "========================================"
ruff check --extend-select I,RUF100 --fix .
ruff format .

echo ""
echo "========================================"
echo "[2/4] 執行 Pylint 靜態分析..."
echo "========================================"
pylint --load-plugins=pylint.extensions.docparams --enable=useless-suppression backend/ crawler/ cli.py scripts/ test/

echo ""
echo "========================================"
echo "[3/4] 執行 Mypy 靜態型別檢查..."
echo "========================================"
mypy --explicit-package-bases backend/ crawler/ cli.py scripts/ test/

echo ""
echo "========================================"
echo "[4/4] 執行 Pytest 整合測試..."
echo "========================================"
pytest test/ -v

echo ""
echo "恭喜！所有檢查與測試皆已完美通過 (All checks passed)！"
