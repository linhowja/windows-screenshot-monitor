# Windows Screenshot Monitor — 完整規格與實作現況

> 本文件整理目前 `mvp-v1` 分支（約 2026-11-24）的需求、規格、安裝行為、設定模型與已知限制。  
> 若與舊文件 `docs/01_MVP_SPEC.md` 衝突，以本文件與目前程式為準。

---

## 1. 專案定位

家庭內由管理者授權的 Windows 10/11 64-bit 電腦，定時截主螢幕，壓成灰階 JPEG，經區域網路送到同一台 Windows Server，再用檔案總管依時間查看。

```text
使用者登入
  -> Client 由工作排程器啟動（登入時，不做 Windows Service）
  -> 本次 process 先等一次隨機 7–30 秒，再做第一次截圖
  -> 只有桌面可用、未鎖定、未睡眠才截圖
  -> 只截 Primary Monitor，保留原始解析度
  -> 8-bit 灰階 JPEG（品質預設 40，範圍 20–100）
  -> POST http://<ServerIPv4>:55550/api/upload
  -> Server 寫完並確認檔案存在後才回 HTTP 200
  -> Client 丟棄這張圖
```

正常網路時，Client 不保存已成功上傳的圖片。只有上傳失敗才進入本機 Cache。

---

## 2. 元件與檔案

| 檔案 | 責任 |
|------|------|
| `app.py` | Client：截圖、壓縮、上傳、Cache、設定載入、鎖定 |
| `client_config_gui.py` | Client 設定視窗（安裝後為 `RuntimeHostConfig.exe`） |
| `server.py` | Server：接收上傳、寫檔、設定、保留檢查、每客戶端設定 |
| `server_config_gui.py` | Server 本機設定視窗（安裝後為 `ScreenshotServerConfig.exe`） |
| `windows_events.py` | 登入、鎖定、睡眠、喚醒 |
| `packaging/` | PyInstaller 與 Inno Setup |

舊檔（不要使用）：

- `tor_server.py`：舊 TorCap 伺服器
- `install.bat`：舊 TorCap 安裝腳本
- 根目錄 `config.json`：舊 TorCap 範本，現在 Client 不讀它

---

## 3. Client

### 3.1 平台與身分

- Windows 10 / Windows 11 64-bit
- 自動取得 Hostname + Windows Username
- Server 上的身分名稱：`Hostname_WindowsUsername`（例如 `LIN-PC01_child`）
- 不要求安裝者輸入 Client ID

### 3.2 啟動

- 使用者登入後由工作排程器啟動
- 工作名稱：`Runtime Host`
- 觸發：At log on
- 主體：Users 群組，RunLevel Limited
- 不是 Windows Service
- 每次 process 啟動只抽一次 7–30 秒隨機延遲，等完才做第一次截圖

### 3.3 安裝位置與隱藏

```text
主程式：C:\ProgramData\Microsoft\Windows\RuntimeHost\RuntimeHost.exe
設定程式：C:\ProgramData\Microsoft\Windows\RuntimeHost\RuntimeHostConfig.exe
（資料夾設為隱藏 + 系統屬性）
```

設定與 Cache：

```text
C:\ProgramData\ScreenshotClient\config.json
C:\ProgramData\ScreenshotClient\Cache\
```

日誌：

```text
Documents\ScreenshotClient\Logs\YYYYMMDD_HHMMSS_CC.LOG
```

### 3.4 截圖條件

**截圖時：**

- 使用者已登入
- 互動桌面可用
- Session 未鎖定
- 系統未睡眠

**停止截圖時：**

- Windows Lock
- Windows Sleep
- Windows Logoff

**恢復時：**

- Unlock / Wake 且桌面可用後，觸發一次 Recovery，不立即補拍
- 下一張等完整 interval

### 3.5 影像處理

固定順序：

```text
Capture → 保留原始解析度 → 8-bit grayscale → JPEG encode → Upload
```

- 只抓 Primary Monitor
- JPEG quality：20–100，預設 40
- 檔名：`YYYYMMDD_HHMMSS_CC.jpg`（CC 是百分之一秒，不是序號）

### 3.6 上傳

- Endpoint：`POST http://<server_ip>:55550/api/upload`
- Timeout：固定 5 秒
- 只有 HTTP 200 算成功
- 成功後丟棄記憶體中的圖片
- 失敗（連線錯誤、timeout、非 200）進入 Cache

### 3.7 Cache 與 Recovery

- Cache 路徑：`C:\ProgramData\ScreenshotClient\Cache\YYYYMMDD\`
- 有檔案 = 待上傳
- 每 300 秒掃一次，由舊到新補傳
- Unlock / Wake 且桌面可用後立即觸發一次
- 成功一張就刪一張
- 超過 `client_cache_days`（預設 7 天）的未上傳檔會刪除
- Recovery 不阻塞正常截圖計時

### 3.8 設定模型與鎖定

Client 設定檔：`C:\ProgramData\ScreenshotClient\config.json`

```json
{
  "server_ip": "192.168.1.10",
  "server_port": 55550,
  "screenshot_interval": 20,
  "jpeg_quality": 40,
  "client_cache_days": 7,
  "locked": false
}
```

優先順序：

```text
明確 CLI override > Last Known Good / Server 推送 > 內建預設
```

**鎖定規則（2026-11-24 加入）：**

- 第一次成功連上 Server（HTTP 200）後，`locked` 設為 `true`
- 鎖定後，`RuntimeHostConfig.exe` 拒絕開啟與儲存，並顯示訊息要求解除安裝後重裝
- Server 推送的間隔、品質、快取天數仍可由程式更新
- 要改設定（尤其是 server_ip）必須解除安裝後重新安裝

### 3.9 權限

- 安裝資料夾：Users 只有讀取／執行
- `config.json`：Users 可修改（讓 Client 程式能寫入鎖定旗標與 Last Known Good）
- 工作排程器任務檔：Users 只有讀取，不易停用或刪除
- 設定程式要求管理員權限（UAC）

---

## 4. Server

### 4.1 平台與監聽

- Windows 64-bit
- 固定監聽 `0.0.0.0:55550`
- Port 不是設定項

### 4.2 安裝位置

```text
程式：C:\Program Files\Windows Screenshot Monitor\Server\
設定：C:\ProgramData\ScreenshotServer\server_config.json
每客戶端設定：C:\ProgramData\ScreenshotServer\clients\<Hostname_Username>\config.json
```

### 4.3 全域設定

`server_config.json`：

```json
{
  "storage_root": "D:\\ScreenshotServer",
  "screenshot_interval": 20,
  "jpeg_quality": 40,
  "client_cache_days": 7,
  "server_image_retention_days": 14
}
```

- `storage_root`、`server_image_retention_days` 是 Server 自己的設定
- 間隔、品質、快取天數是「新客戶端的預設範本」

### 4.4 每客戶端設定（2026-11-24 加入）

每一台客戶端在 Server 電腦上有自己的設定檔：

```text
C:\ProgramData\ScreenshotServer\clients\
└── LIN-PC01_child\
    └── config.json
```

內容：

```json
{
  "screenshot_interval": 20,
  "jpeg_quality": 40,
  "client_cache_days": 7
}
```

行為：

- 客戶端第一次成功上傳時，用目前全域預設建立該檔
- 之後每次上傳成功，回傳該客戶端自己的設定
- 在 Server 上直接改這個檔，下次該客戶端上傳成功就會套用
- 改全域設定只影響「之後新連上的客戶端」，不自動改已存在的客戶端

### 4.5 儲存結構

```text
<StorageRoot>\
└── Hostname_WindowsUsername\
    └── YYYYMMDD\
        └── YYYYMMDD_HHMMSS_CC.jpg
```

- 同名檔已存在時視為成功（HTTP 200），不覆蓋、不另存
- 路徑限制在 Storage Root 內，防止 path traversal

### 4.6 上傳成功回應

```json
{
  "status": "ok",
  "config": {
    "screenshot_interval": 20,
    "jpeg_quality": 40,
    "client_cache_days": 7
  }
}
```

`config` 來自該客戶端自己的設定檔。

### 4.7 圖片保留

- `server_image_retention_days` 預設 14 天
- 不是背景自動刪除
- 每個本機日期第一次啟動時檢查，使用者確認（Yes）才刪除本次掃描清單
- 只處理正式階層的 `.jpg`，用檔名時間戳計算年齡

### 4.8 防火牆

安裝時建立入站規則：

```text
Name: Screenshot Server
Direction: Inbound
Protocol: TCP
Local Port: 55550
Action: Allow
```

Client 不建立入站規則。

---

## 5. 安裝與解除安裝

### 5.1 Client 安裝時會做的事

1. 清掉舊版：
   - 工作：`Screenshot Client`、`Runtime Host`
   - 目錄：`C:\Program Files\Windows Screenshot Monitor\`、`Program Files (x86)` 對應路徑
   - 開始功能表捷徑
   - `C:\ProgramData\ScreenshotClient`
2. 安裝到 `C:\ProgramData\Microsoft\Windows\RuntimeHost\`
3. 設定隱藏屬性
4. 寫入新的 `config.json`（含安裝時輸入的 Server IP）
5. 設定權限
6. 註冊工作排程器「Runtime Host」並限制一般使用者修改

### 5.2 Server 安裝

- 安裝到 `C:\Program Files\Windows Screenshot Monitor\Server`
- 要求 Storage Root
- 建立防火牆規則
- 建立 `ScreenshotServerConfig.exe` 捷徑

### 5.3 解除安裝

- Client：移除程式、工作、已知舊路徑；是否刪 ProgramData 在解除安裝時詢問
- Documents 日誌預設不刪
- Server：移除程式與防火牆規則；Storage Root 資料預設不因解除安裝而直接刪除

---

## 6. 設定同步流程

```text
Client 上傳成功
  -> Server 回傳該客戶端的 config
  -> Client 驗證後更新 runtime 與 Last Known Good
  -> 同時把 locked 設為 true
  -> 下一次等待與下一張截圖使用新的 interval / quality
```

Server 離線時，Client 繼續用最後有效設定，不退回預設值，也不停止工作。

---

## 7. 已知限制與未實作項目

| 項目 | 狀態 |
|------|------|
| 從 Server 強迫更新 Client 執行檔 | 未實作。目前只能推送設定 |
| Server GUI 管理個別客戶端設定 | 未實作。需直接編輯 `clients\<identity>\config.json` |
| 直接用記事本改 Client config.json | 技術上仍可能（因為程式需要寫入權限），但設定視窗已被鎖定擋下 |
| 身分驗證、TLS | 未實作 |
| 多 Client 管理介面 | 未實作 |
| Web UI / 圖片瀏覽 | 未實作。用檔案總管查看 |
| 做成 Windows Service | 不適合。截圖需要使用者互動桌面 |

---

## 8. 建置與打包

```text
py -3 -m pip install -r requirements.txt pyinstaller
py -3 -m PyInstaller packaging/client.spec          # -> dist/RuntimeHost.exe
py -3 -m PyInstaller packaging/client_config.spec   # -> dist/RuntimeHostConfig.exe
py -3 -m PyInstaller packaging/server.spec
py -3 -m PyInstaller packaging/server_config.spec
```

再用 Inno Setup 編譯 `packaging/client.iss` 與 `packaging/server.iss`。

或在 GitHub Actions 用 `Build Windows installers` workflow（workflow_dispatch，mvp-v1）。

---

## 9. 檢查紀錄（2026-11-24）

本次從頭檢查發現並修正：

- `client_config_gui.py` 的 self-test 仍檢查舊的 `ScreenshotClientConfig.exe` 名稱，與目前打包設定不符，會導致 self-test 失敗。已改為檢查 `RuntimeHostConfig.exe`。

其他主要邏輯（鎖定、每客戶端設定、安裝清理、權限、工作排程）與目前設計一致，未發現會導致功能錯誤的明顯 bug。

---

## 10. 相關文件

- `docs/01_MVP_SPEC.md`：早期 MVP 規格（部分內容已過時）
- `docs/05_PHASE_HISTORY.md`：各階段實作與除錯紀錄
- `packaging/BUILD.txt`：建置與安裝路徑說明
- 本文件：目前完整現況


## A-01 update

### 3.8 設定模型（A-01，方案甲）

兩份檔案：

| 檔案 | 路徑 | Users 權限 | 內容 |
|------|------|------------|------|
| `install_config.json` | `C:\ProgramData\Microsoft\Windows\RuntimeHost\` | RX（繼承資料夾） | `server_ip`, `server_port` |
| `runtime_state.json` | `C:\ProgramData\ScreenshotClient\` | M | 間隔、品質、快取天數 |

- Client 程式只讀 `install_config.json`，永不寫回。
- Server 推送只更新 `runtime_state.json`。
- 一般使用者無法修改或刪除 `install_config.json`。
- 管理員用 `RuntimeHostConfig.exe`（UAC）可改 `server_ip`。
- GUI 中三個動態參數為唯讀，由 Server 的 `clients\<identity>\config.json` 管理。
- 不再使用 `locked` 旗標。

優先順序：

```text
明確 CLI override > Last Known Good / Server 推送 > 內建預設
```

### 3.9 權限

- 安裝資料夾：Users 只有讀取／執行（`install_config.json` 繼承此權限）
- `runtime_state.json`：Users 可修改（讓 Client 程式能寫入 Server 推送的值）
- 工作排程器任務檔：Users 只有讀取，不易停用或刪除
- 設定程式要求管理員權限（UAC）


## 下一版安裝要求（待實作）

Client 安裝精靈在按「下一步」完成安裝前，必須先確認能連上所填的 Server：

1. 使用者輸入 Server IPv4 後，安裝程式對該 IP 的 TCP 55550 做連線測試。
2. 連不上則顯示錯誤，不允許進入下一步，也不寫入設定、不建立工作排程器。
3. 連得上才繼續安裝，並寫入 `install_config.json`。

原因：1.2 實機安裝時，安裝腳本中途中斷，`install_config.json` 沒寫入，Client 用預設 127.0.0.1，Server 收不到任何訊號。連線確認可避免裝完卻完全連不上。

個人使用預設 Server IP：`172.16.0.200`。
