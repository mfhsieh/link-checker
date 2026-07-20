#!/bin/bash
# 系統與專案磁碟空間清理腳本
# 依據 doc/deploy_gcp_vm.md 與 PostgreSQL 轉移後的狀況清理不必要的檔案

set -e

echo "============================================="
echo " 開始執行磁碟空間清理作業..."
echo "============================================="

echo "--- 清理前根目錄使用狀況 ---"
df -h /
echo

# 1. 清除 APT 依賴套件與下載快取
echo "[1/4] 清除不再使用的 APT 依賴套件與快取..."
sudo apt autoremove --purge -y
sudo apt clean

# 2. 清除舊版的 Snap 套件與快取
echo "[2/4] 清除舊版 Snap 套件與下載快取..."
sudo sh -c 'set -eu; snap list --all | awk "/disabled/{print \$1, \$3}" | while read snapname revision; do snap remove "$snapname" --revision="$revision"; done' || true
sudo find /var/lib/snapd/cache -mindepth 1 -delete || true

# 3. 清理龐大的 systemd 系統日誌
echo "[3/4] 清理 systemd 系統日誌 (僅保留最近 28 天)..."
sudo journalctl --vacuum-time=28d 2>/dev/null

echo "--- 清理中根目錄使用狀況 ---"
df -h /
echo
echo "--- 清理前資料庫佔用空間 ---"
sudo -u postgres psql -t -c "SELECT 'crawler_db: ' || pg_size_pretty(pg_database_size('crawler_db'));" 2>/dev/null | xargs || true
sudo -u postgres psql -t -c "SELECT 'auth_db: ' || pg_size_pretty(pg_database_size('auth_db'));" 2>/dev/null | xargs || true
echo

# 4. 針對 Crawler DB 進行無鎖定「化整為零」空間重組 (pg_repack)
# 確保磁碟已被充分清理後再執行，避免空間不足。這裡採用「逐表」與「僅索引」的方式。
echo "[4/4] 執行資料庫空間重組 (pg_repack)..."
if command -v pg_repack >/dev/null 2>&1; then
    echo "  -> 檢查到 pg_repack，開始針對資料庫進行兩階段無鎖重組..."
    
    # 1. 優先重組空間極小的 auth_db，一次全部重組
    echo "  -> [auth_db] 進行全庫重組..."
    sudo -u postgres pg_repack -d auth_db || true
    
    # 2. 針對 crawler_db，依照資料表大小 (小 -> 大) 逐一進行「先 Index 再 Table」重組
    echo "  -> [crawler_db] 進行兩階段重組 (先重組索引瘦身，再重組資料表)..."
    
    # Table 1: jobs (最小)
    sudo -u postgres pg_repack -x -t jobs -d crawler_db || true
    sudo -u postgres pg_repack -t jobs -d crawler_db || true
    
    # Table 2: crawl_queue (中等)
    sudo -u postgres pg_repack -x -t crawl_queue -d crawler_db || true
    sudo -u postgres pg_repack -t crawl_queue -d crawler_db || true
    
    # Table 3: external_links (最大)
    sudo -u postgres pg_repack -x -t external_links -d crawler_db || true
    sudo -u postgres pg_repack -t external_links -d crawler_db || true
    
    echo "  -> 資料庫空間重組完成。"
else
    echo "  -> [提示] 系統尚未安裝 pg_repack，略過資料庫重組。"
    echo "  -> 若需啟用，請先執行: sudo apt install postgresql-<版本>-repack"
fi

echo "--- 清理後根目錄使用狀況 ---"
df -h /
echo
echo "--- 清理後資料庫佔用空間 ---"
sudo -u postgres psql -t -c "SELECT 'crawler_db: ' || pg_size_pretty(pg_database_size('crawler_db'));" 2>/dev/null | xargs || true
sudo -u postgres psql -t -c "SELECT 'auth_db: ' || pg_size_pretty(pg_database_size('auth_db'));" 2>/dev/null | xargs || true
echo

echo "============================================="
echo " 清理完成！"
echo "您可以透過執行 df -h 或是透過 MCP 工具查看釋放後的空間。"
echo "============================================="
