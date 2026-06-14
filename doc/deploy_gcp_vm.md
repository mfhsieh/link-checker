# GCP VM 部署指南

本指南將帶您一步步將「外部連結檢查系統」部署到 Google Cloud Platform (GCP) 的虛擬機器 (Compute Engine VM) 上，並設定為可 24 小時運作的背景服務。

## 步驟一：建立 GCP 虛擬機器 (VM Instance)

1. 登入 [GCP 主控台](https://console.cloud.google.com/)，導覽至 **Compute Engine > VM 執行個體**。
2. 點擊 **建立執行個體**。
3. **機器設定**：
   - 建議選擇 `e2-small` 或 `e2-medium`（視您預計掃描的規模而定。因系統實作了記憶體高速聚合去重架構，若需處理百萬級別的連結匯出，建議至少配備 2GB RAM 以上）。
4. **開機磁碟 (Boot Disk)**：
   - 向下捲動找到「開機磁碟」區塊，點擊 **「變更」(Change)** 按鈕。
   - **作業系統 (Operating System)**：在下拉選單中選擇 **Ubuntu**。
   - **版本 (Version)**：選擇 **Ubuntu 24.04 LTS** (LTS 代表長期支援版，穩定性較高，且內建 Python 3.12)。
   - 設定完成後，點擊底部的 **「選取」(Select)** 儲存變更。
5. **防火牆**：
   - 勾選 **允許 HTTP 流量**。
   - 勾選 **允許 HTTPS 流量**。
6. 點擊 **建立**，等待機器啟動完成。

## 步驟二：連線並安裝系統依賴

1. 點擊 VM 列表中的 **SSH** 按鈕，開啟網頁版終端機。
2. 更新系統套件並安裝 Python 3 環境與 Nginx：

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git nginx build-essential python3-dev sqlite3
```

3. **(強烈建議) 建立 Swap 虛擬記憶體**：
   - 若您選擇 `e2-micro` 規格 (僅 1GB RAM)，爬蟲在處理大量網頁時極易觸發 OOM (Out of Memory) 導致服務崩潰。請執行以下指令建立 2GB 的 Swap 交換空間以保障系統穩定運行：

```bash
# 建立一個 2GB 的 swap 檔案
sudo fallocate -l 2G /swapfile
# 設定正確的權限
sudo chmod 600 /swapfile
# 將檔案格式化為 swap
sudo mkswap /swapfile
# 啟用 swap
sudo swapon /swapfile
# (可選) 永久生效，加入 /etc/fstab
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 步驟三：下載專案與安裝 Python 套件

1. 將專案程式碼複製到 VM 中（此處以 `/opt/` 目錄為例，您也可放於家目錄）：

```bash
# 假設將專案放在 /opt/ext-link-checker
sudo mkdir -p /opt/ext-link-checker
sudo chown -R $USER:$USER /opt/ext-link-checker

# 複製您的程式碼至該目錄
git clone <您的 Git 儲存庫網址> /opt/ext-link-checker
cd /opt/ext-link-checker
```

2. 建立虛擬環境 (Virtual Environment) 並安裝套件：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 步驟四：系統環境變數與初始化

1. 複製並設定環境變數檔 `.env`：

```bash
cp .env.example .env
nano .env
```

> **提示**：若您希望自訂資料庫儲存位置（例如掛載至外部硬碟以節省系統碟空間），請於 `.env` 中設定 `AUTH_DB_URL` 與 `CRAWLER_DB_URL`。

2. 初始化系統，建立第一位管理員帳號：

```bash
# 請替換為您的信箱
python cli.py --create-admin admin@example.com
```

> **重要**：請務必記下終端機畫面上顯示的**初始隨機密碼**，以便稍後登入系統。

## 步驟五：設定 Systemd 背景服務

為了讓系統在您關閉 SSH 視窗後繼續運行，甚至在 VM 重開機後自動啟動，我們需要設定 Systemd。

1. 建立服務設定檔：

```bash
sudo nano /etc/systemd/system/ext-link-checker.service
```

2. 貼上以下內容（請確認路徑與您的實際路徑一致）：

```ini
[Unit]
Description=External Link Checker Service
After=network.target

[Service]
User=<您的登入帳號名稱>
Group=<您的登入帳號名稱>
WorkingDirectory=/opt/ext-link-checker
Environment="PATH=/opt/ext-link-checker/.venv/bin"
ExecStart=/opt/ext-link-checker/.venv/bin/python cli.py --serve
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> **資安提醒**：為了確保伺服器安全，`User` 與 `Group` 絕對不建議使用 `root`。請將 `<您的登入帳號名稱>` 替換為您目前登入的 Linux 帳號名稱（可輸入 `whoami` 指令查詢），這必須與您在步驟三設定資料夾權限的帳號一致。

3. 重新載入 Systemd 並啟動服務：

```bash
sudo systemctl daemon-reload
sudo systemctl enable ext-link-checker
sudo systemctl start ext-link-checker
```

4. 檢查服務狀態（確保沒有錯誤）：

```bash
sudo systemctl status ext-link-checker
```

## 步驟六：設定 Nginx 反向代理 (Reverse Proxy)

雖然系統預設運行在 `8000` 埠，但基於安全性與網頁標準，建議使用 Nginx 將 HTTP (80) 導向至內部的 8000 埠。

1. 建立 Nginx 設定檔：

```bash
sudo nano /etc/nginx/sites-available/ext-link-checker
```

2. 貼上以下內容：

```nginx
server {
    listen 80;
    # 若有網域請將 _ 改為您的網域名稱，例如 example.com
    server_name _; 

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 支援長時間運行的請求 (如爬蟲相關操作)
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

3. 啟用設定並重新啟動 Nginx：

```bash
# 移除 Nginx 預設網頁
sudo rm /etc/nginx/sites-enabled/default

# 啟用我們的設定
sudo ln -s /etc/nginx/sites-available/ext-link-checker /etc/nginx/sites-enabled/

# 測試設定是否正確
sudo nginx -t

# 重啟 Nginx
sudo systemctl restart nginx
```

## 步驟七：登入系統

現在，您可以直接在瀏覽器輸入 GCP VM 的**外部 IP 位址**：

```text
http://<您的 VM 外部 IP>/
```

1. 輸入您剛才建立的信箱與終端機上提供的初始隨機密碼登入。
2. 依照系統提示，變更為您專屬的高強度密碼。
3. 恭喜！您已成功完成雲端部署。

---

## 步驟八：設定網域與 HTTPS 安全憑證 (Certbot)

為了確保系統資料（如帳號密碼、爬蟲日誌）傳輸時的機密性，強烈建議您使用 Let's Encrypt 提供的免費 SSL 憑證將 HTTP 升級為 HTTPS。

1. **設定 DNS 紀錄**：
   前往您的網域註冊商 (如 GoDaddy、Cloudflare 等)，新增一筆 **A 紀錄**，將您的網域 (例如 `example.com`) 指向這台 GCP VM 的外部 IP。
2. **修改 Nginx 設定檔**：
   將我們先前設定的 Nginx 設定檔中的 `server_name` 改為您的真實網域。
   ```bash
   sudo nano /etc/nginx/sites-available/ext-link-checker
   # 將 server_name _; 改為 server_name example.com;
   sudo systemctl reload nginx
   ```
3. **安裝 Certbot**：
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   ```
4. **取得並套用憑證**：
   ```bash
   # 請將 example.com 替換為您的真實網域
   sudo certbot --nginx -d example.com
   ```
   執行後，Certbot 會要求您輸入 Email 並同意服務條款，接著會自動幫您修改 Nginx 設定檔，強制將 HTTP 導向 HTTPS。
5. **驗證自動更新機制**：
   Let's Encrypt 憑證有效期為 90 天，Certbot 會自動建立排程幫您展期。您可以檢查自動更新計時器是否正常運作：
   ```bash
   sudo systemctl status certbot.timer
   ```

---

## 進階：使用 PuTTY 連線至 VM (Windows 用戶)

如果您不習慣使用網頁版的 SSH，希望透過本機的 PuTTY 軟體連線，請依照以下步驟設定 SSH 金鑰：

### 1. 產生 SSH 金鑰 (使用 PuTTYgen)
1. 下載並安裝 [PuTTY 官方套件](https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html)（會包含 `PuTTYgen`）。
2. 開啟 **PuTTYgen**。
3. 點擊 **Generate**，並在空白處隨機移動滑鼠直到進度條完成。
4. **Key comment**：這個欄位非常重要！請輸入您想要的 **Linux 登入帳號名稱**（建議使用全小寫英文，例如 `myuser`）。
5. 點擊 **Save private key**，將私鑰存成 `.ppk` 檔案，妥善保存在您的電腦中。
6. **複製公鑰**：將畫面上方 `Public key for pasting into OpenSSH authorized_keys file:` 框框內的所有文字（通常以 `ssh-rsa ...` 開頭）完整複製下來。

### 2. 將公鑰加入 GCP VM
1. 回到 GCP 主控台的 **Compute Engine > VM 執行個體** 列表。
2. 點擊您的 VM 名稱進入詳情頁面，然後點擊上方選單的 **編輯 (Edit)**。
3. 向下捲動找到 **SSH 金鑰 (SSH Keys)** 區塊。
4. 點擊 **新增項目 (Add item)**，將剛才在 PuTTYgen 複製的「公鑰」文字貼上。
5. 貼上後，旁邊應該會自動顯示您在 Key comment 設定的登入帳號名稱。
6. 捲動到最下方，點擊 **儲存 (Save)**。

### 3. 使用 PuTTY 連線
1. 開啟 **PuTTY** 主程式。
2. 在 **Session** 類別頁面：
   - **Host Name (or IP address)**：輸入您的 VM 外部 IP。
3. 在左側清單導覽至 **Connection > Data**：
   - **Auto-login username**：輸入您剛才設定的登入帳號名稱（Key comment）。
4. 在左側清單導覽至 **Connection > SSH > Auth > Credentials**（舊版 PuTTY 可能只有 **Auth**）：
   - 點擊 **Browse...**，選擇您剛剛儲存的 `.ppk` 私鑰檔案。
5. （選填）回到 **Session** 頁面，在 `Saved Sessions` 欄位輸入一個名稱（例如 GCP VM），點擊 **Save** 儲存這些設定，下次點兩下就能連線。
6. 點擊 **Open**。
7. 第一次連線時會出現安全警告，點擊 **Accept (是)** 即可成功連入您的 VM！

> **提示**：若透過 PuTTY 連入，您的家目錄會是 `/home/<您的登入帳號名稱>/`。如果您先前將專案放在 `/opt/ext-link-checker`，請記得執行 `cd /opt/ext-link-checker` 進入專案資料夾。

---

## 維護與更新：如何更新系統程式碼

當專案程式碼有更新，或者您修復了某些 Bug 需要部署至伺服器時，請依照以下標準流程在 GCP VM 上拉取最新程式碼並重啟服務：

1. **進入專案目錄**：
   ```bash
   cd /opt/ext-link-checker
   ```
2. **停止背景服務**：
   ```bash
   sudo systemctl stop ext-link-checker
   ```
3. **拉取最新程式碼**：
   ```bash
   git pull
   ```
4. **更新 Python 依賴套件 (防範 requirements.txt 有變更)**：
   ```bash
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
5. **重新啟動背景服務**：
   ```bash
   sudo systemctl start ext-link-checker
   ```
6. **確認服務狀態**：
   ```bash
   sudo systemctl status ext-link-checker
   ```
   若看到綠色的 `active (running)` 字樣，即代表系統更新並重啟成功！

---

## 進階維護：資料庫空間釋放 (VACUUM)

在系統長期運行過程中，當您刪除了大量的爬蟲任務或歷史日誌後，SQLite 資料庫檔案的大小預設並不會自動縮小。為了釋放未使用的實體磁碟空間，建議定期手動執行 `VACUUM` 指令。

1. **進入專案目錄**：
   ```bash
   cd /opt/ext-link-checker
   ```
2. **執行 VACUUM 壓縮資料庫**：
   ```bash
   # 壓縮爬蟲資料庫 (若有自訂 CRAWLER_DB_URL，請替換為該路徑)
   sqlite3 db/crawler.db "VACUUM;"

   # 壓縮帳號資料庫 (若有自訂 AUTH_DB_URL，請替換為該路徑)
   sqlite3 db/auth.db "VACUUM;"
   ```

> **💡 建議時機**：執行 `VACUUM` 期間會產生較高的磁碟 I/O 負載並短暫鎖定資料庫，建議在系統的離峰時間，或是在您剛從後台刪除了大量舊任務後手動執行。您也可以將這兩行指令寫入 Linux 的 Cronjob 進行每週或每月的定期排程維護。