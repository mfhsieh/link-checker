#!/bin/bash
# ==============================================================================
# 腳本名稱: job_sync.sh
# 腳本說明: 任務匯出與匯入的 Shell Script 便利包
# 
# 主要功能:
#   提供易用的命令列介面來執行任務資料庫與結果的備份 (export) 與復原 (import)。
#   本腳本會自動檢查並啟動專案內的 `.venv` 虛擬環境，然後呼叫 
#   `scripts/manage_job_data.py` 來進行實際的資料處理。
#
# 執行環境:
#   - 需要在專案根目錄下，或是透過絕對路徑呼叫此腳本。
#   - 必須確保專案目錄下已建立 `.venv` 虛擬環境。
# ==============================================================================

show_help() {
    echo "使用方式:"
    echo "  匯出: ./scripts/job_sync.sh export <要備份的 JOB_ID> <存放備份的資料夾路徑>"
    echo "  匯入: ./scripts/job_sync.sh import <存放備份的資料夾路徑> <接手人的 USER_ID>"
    echo ""
    echo "範例:"
    echo "  ./scripts/job_sync.sh export 5eebf2ac-250f-463d-a4cc-98a64d50b5fc ./backup_job_data"
    echo "  ./scripts/job_sync.sh import ./backup_job_data user-uuid-1234"
}

if [ -z "$1" ] || [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    show_help
    exit 0
fi

COMMAND=$1

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/.." || exit 1

if [ ! -d ".venv" ]; then
    echo "錯誤: 找不到 .venv 虛擬環境，請確認您在專案根目錄且已建立虛擬環境。"
    exit 1
fi

source .venv/bin/activate

if [ "$COMMAND" == "export" ] || [ "$COMMAND" == "import" ]; then
    if [ -z "$2" ] || [ -z "$3" ]; then
        echo "錯誤: 缺少必要參數。"
        show_help
        exit 1
    fi
    python scripts/manage_job_data.py "$COMMAND" "$2" "$3"
else
    echo "錯誤: 無效的指令 '$COMMAND'"
    echo "請使用 'export' 或 'import' 作為第一個參數。"
    show_help
    exit 1
fi