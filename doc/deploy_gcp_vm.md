# GCP VM 部署指南

本指南將帶您一步步將「外部連結檢查系統」部署到 Google Cloud Platform (GCP) 的虛擬機器 (Compute Engine VM) 上，並設定為可 24 小時運作的背景服務。

## 步驟一：建立 GCP 虛擬機器 (VM Instance)

1. 登入 [GCP 主控台](https://console.cloud.google.com/)，導覽至 **Compute Engine > VM 執行個體**。
2. 點擊 **建立執行個體**。
3. **機器設定**：
   - 建議選擇 `e2-micro` 或 `e2-small`（視您預計掃描的規模而定，若是大量並行掃描建議至少 2GB RAM）。
4. **開機磁碟**：
   - 點擊「變更」。
   - 作業系統選擇 **Ubuntu**。
   - 版本選擇 **Ubuntu 24.04 LTS** 或 **Ubuntu 22.04 LTS**（內建 Python 3.10+）。
   - 磁碟大小建議至少 20 GB。
5. **防火牆**：
   - 勾選 **允許 HTTP 流量**。
   - 勾選 **允許 HTTPS 流量**。
6. 點擊 **建立**，等待機器啟動完成。

## 步驟二：連線並安裝系統依賴

1. 點擊 VM 列表中的 **SSH** 按鈕，開啟網頁版終端機。
2. 更新系統套件並安裝 Python 3 環境與 Nginx：

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git nginx
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

> **注意**：請務必在 `.env` 中設定一組高強度的隨機字串作為 `SECRET_KEY`，並設定您的 SMTP 寄信參數，確保 `DEBUG=false`。

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
User=root
Group=root
WorkingDirectory=/opt/ext-link-checker
Environment="PATH=/opt/ext-link-checker/.venv/bin"
ExecStart=/opt/ext-link-checker/.venv/bin/python cli.py --serve
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

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

*(建議後續可將網域指向該 IP，並使用 Certbot (Let's Encrypt) 加上免費的 SSL (HTTPS) 安全憑證。)*