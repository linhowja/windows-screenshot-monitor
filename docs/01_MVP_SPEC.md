# Windows Screenshot Monitor — MVP Specification v1.0

## 1. 定位

單一家庭網路環境使用的 Windows 64-bit Screenshot Client + Windows 64-bit Screenshot Server。

目標：

```text
Windows Client
    -> 定時截圖
    -> 影像處理
    -> HTTP POST
    -> Windows Server
    -> 檔案系統保存
```

正常網路時，Client 不保存已成功上傳圖片；只有 Upload Failed 時才進入 Local Cache。

## 2. Client

### Platform

- Windows 10 / Windows 11 64-bit
- 第一版以單一 Client 為主，但設計不要阻止未來多 Client

### Identity

Client 啟動後自動取得：

- Hostname
- Windows Username

Server 的資料來源名稱：

```text
Hostname_WindowsUsername
```

例如：

```text
LIN-PC01_child
```

不要求安裝者輸入 Client ID。

### Startup

- 使用者登入後自動啟動
- 建議使用 Windows Task Scheduler: `At log on`
- 可以是 `Any user`
- `Run only when user is logged on`
- 不需要 Windows Service

### UI

Client：

- 不建立 Desktop Shortcut
- 不建立 Tray Icon
- 不顯示一般操作視窗
- 正常背景執行
- 必須可由 Windows 正常管理及解除安裝
- 不實作 rootkit、程序隱藏、規避防毒/EDR 或其他 stealth/evasion 技術

## 3. Capture state

### Capture when

- 使用者已登入
- Desktop/interactive session 已可用
- Session 未鎖定
- 系統未進入 Sleep

### Stop capture when

- Windows Lock
- Windows Sleep
- Windows Logoff

### Resume when

- Unlock
- Wake from Sleep
- 且使用者仍登入、Session 已可使用

Unlock / Wake 後應恢復正常計時，不要求解鎖瞬間立即產生額外截圖。

### Windows events

實作可優先使用 Windows session notification 與 power notification，而不是高頻率輪詢狀態。

## 4. Screen

- 只抓 Primary Monitor
- 不處理多螢幕

## 5. Image processing

固定處理順序：

```text
Capture
  -> Keep original resolution
  -> 8-bit Grayscale
  -> JPEG encode
  -> Upload
```

輸出影像維持 Primary Monitor 擷取時的原始寬度與高度，不進行解析度縮放。

例如：

```text
1024 x 768  -> 1024 x 768
1920 x 1080 -> 1920 x 1080
2560 x 1440 -> 2560 x 1440
```

### JPEG quality

- Server 可設定
- 合法範圍：20–100
- 預設：40

MVP 不需要 GIF。

## 6. Screenshot interval

- Server 可設定
- 預設：20 秒

Client 應使用最後一次成功取得的有效設定。

## 7. Filename

格式：

```text
YYYYMMDD_HHMMSS_CC.jpg
```

其中：

- YYYY = 年
- MM = 月
- DD = 日
- HH = 時
- MM = 分
- SS = 秒
- CC = 百分之一秒（厘秒，00–99）

範例：

```text
20261003_162000_37.jpg
```

`CC` 不是序號。

極端情況若產生完全相同 timestamp，Server 必須避免資料覆蓋，但不要把正常檔名設計成 `_01`, `_02` 序號制。

## 8. Server

### Platform

Windows 64-bit。

### Listen port

```text
TCP 55550
```

MVP 固定，不列為一般 Server 設定項目。

### Storage Root

最上層資料夾由使用者：

- 安裝時設定
- 或進入 Server 設定後修改

例如：

```text
D:\ScreenshotServer\
```

程式安裝位置與資料位置分離。

例如：

```text
C:\Program Files\ScreenshotServer\
D:\ScreenshotServer\
```

修改 Storage Root 時：

- 只影響未來新資料
- 不自動搬移舊資料

### Storage layout

```text
<StorageRoot>\
└── Hostname_WindowsUsername\
    └── YYYYMMDD\
        ├── YYYYMMDD_HHMMSS_CC.jpg
        └── ...
```

## 9. HTTP upload

Endpoint：

```text
POST /api/upload
```

Content-Type：

```text
multipart/form-data
```

Client 至少傳：

- hostname
- username
- file

Server 不需要 Client 額外傳 `day`；Server 應由 filename 的前 8 碼解析日期。

Server 負責組合實際檔案路徑。

## 10. Upload success / ACK

Server 只有在：

1. 輸入驗證成功
2. 日期目錄可建立
3. 圖片成功寫入最終位置
4. Server 可確認檔案已存在

之後才回：

```text
HTTP 200
```

例如：

```json
{
  "status": "ok",
  "config": {
    "screenshot_interval": 20,
    "jpeg_quality": 40,
    "client_cache_days": 3
  }
}
```

Client 只把 HTTP 200 視為 upload 成功。config 驗證失敗時，本次 upload 仍算成功，但不取代 Last Known Good。

## 11. Upload timeout

固定：

```text
5 seconds
```

第一版不讓 Server 設定此值。

若 5 秒內沒有成功回應：

```text
Upload Failed
```

Client 必須繼續工作，不因單張上傳 timeout 而停止 capture。

## 12. Normal upload behavior

正常網路：

```text
Capture
 -> Grayscale
 -> JPEG
 -> HTTP POST
 -> Server writes successfully
 -> HTTP 200
 -> Client discards image
```

正常成功的圖片不應先寫入永久 Local Storage。

可以先存在記憶體中；成功後釋放。

## 13. Offline / failed upload behavior

以下均視為上傳失敗：

- network connection error
- timeout
- HTTP non-200
- server unavailable

失敗後：

```text
Screenshot
 -> Local Cache
```

Client 必須繼續截圖。

## 14. Local Cache

Cache 直接作為 upload queue。

不使用 SQLite。

概念：

```text
Cache\
└── YYYYMMDD\
    ├── *.jpg
    └── ...
```

有檔案 = 待上傳。

### Client Cache retention

- 由 Server 設定
- 預設：3 Days
- 只針對尚未成功上傳的 Local Cache
- 超過保留期限，自動刪除

MVP 暫不處理特殊 ACL / Cache 權限保護。

## 15. Recovery

### No high-frequency ping

不要每秒或每幾秒 Ping Server。

### Normal screenshot attempt

每次截圖本身即自然嘗試一次 Upload。

### Recovery scan

每 5 分鐘：

```text
Scan Local Cache
 -> 沒有檔案：結束
 -> 有檔案：開始補傳
```

### Unlock / Wake

Unlock / Wake 且確認 Session 可用後：

```text
立即觸發一次 Recovery Scan
```

### Recovery order

- 最舊 -> 最新
- 全部補傳
- 成功一張即從 Cache 移除一張
- 不刻意限制「一次最多幾張」
- Recovery 不得阻塞正常 Screenshot Timer

## 16. Duplicate upload protection

必須支援重複 Upload 不造成第二份正常檔案。

情境：

```text
Server 已寫檔
 -> response 丟失
 -> Client 5 秒 timeout
 -> Client Cache
 -> 後續重新上傳同一檔案
```

Server 發現相同 Client identity + date + filename 已存在時，可以直接視為成功並回 HTTP 200，而不是產生 `_1`, `_2` 檔名。

## 17. Client configuration model

Client 初次啟動至少知道：

- Server IPv4。未指定 `--server-ip` 時使用 Last Known Good；只有明確指定才覆寫。第一次沒有 LKG 才用 127.0.0.1
- Server Port = 55550

Windows 正式 Last Known Good 檔案：

```text
C:\ProgramData\ScreenshotClient\config.json
```

內容包含 `server_ip`、`server_port`、`screenshot_interval`、`jpeg_quality`、`client_cache_days`。寫入必須先寫暫存檔，再 `flush/fsync` 後 `os.replace()`。

優先順序：

```text
explicit CLI override > Last Known Good / current server config > built-in default
```

未明確指定 `--interval` 或 `--quality` 時，不得用 parser default 蓋過 Last Known Good。

Server 設定檔是 `server_config.json`，包含 `storage_root`、`screenshot_interval`、`jpeg_quality`、`client_cache_days`、`server_image_retention_days`。優先順序是 explicit `--storage-root` > config file > default。Port 仍固定 55550。損壞或不合法的設定不得讓 Server 無法啟動。

## 18. Server configuration synchronization

Server 是設定來源，但 Client 不依賴 Server 才能運作。

正常 upload 成功時，HTTP 200 帶回目前有效的 Client 設定。不傳 `storage_root` 或 `server_image_retention_days`。Client 驗證成功後才更新 runtime 與 Last Known Good。下一次等待與下一張截圖使用更新後的 interval 與 quality；明確指定的 CLI override 仍優先。Server 離線時繼續使用最後有效設定，不退回預設值。Duplicate upload 的 HTTP 200 也帶同一份 config。`python server.py --self-test` 可不帶 `--storage-root`，正式啟動的優先順序仍是 `--storage-root` > `server_config.json` > default。

## 19. Server unavailable behavior

若 Server：

- 關機
- 無回應
- timeout
- network failure

Client：

- 不停止
- 繼續使用最後有效設定
- 繼續截圖
- 失敗圖片進 Cache

## 20. Client identity / server registration

MVP 不做：

- Client Registration
- Client Token
- Client Password
- Client approval workflow
- Client database

任何能連到 TCP 55550 且符合資料格式的 Client，都可直接建立對應資料夾。

但 Server 必須驗證：

- hostname
- username
- filename
- date format
- file path safety
- file type / upload validity

必須防止 path traversal。

## 21. Server image retention

`server_image_retention_days` 是提醒與刪除判斷門檻，預設 14 天。Server 不會在背景自動刪除圖片。

每個本機日期只檢查並詢問一次。狀態存在 `server_config.json` 同一層的 `server_retention_state.json`，不放在 Storage Root。

啟動順序：

```text
load config
→ retention check / confirmation
→ start HTTP server
```

只有符合正式 storage hierarchy、檔名日期有效、且檔名日期與 date directory 相同的 `.jpg`，才可能成為候選。年齡以 filename timestamp 計算，不用 filesystem mtime。只有嚴格超過 retention days 才詢問。

使用者選 Yes 才刪除本次掃描清單。選 No、關閉視窗或無法取得選擇時完全保留，並提醒自行搬移。非正式 hierarchy、`.tmp`、其他副檔名與日期錯誤檔案永不因 Retention 刪除。

## 22. Server GUI

MVP 不做 Web UI。

圖片直接由 Windows File Explorer 查看：

```text
Large Icons
Extra Large Icons
```

Server 本機可以有一個極簡設定介面，用來修改：

- Storage Root
- Screenshot Interval
- JPEG Quality
- Client Cache Retention
- Server Image Retention

不做圖片瀏覽功能。

## 23. Firewall

### Server

安裝時自動檢查 Windows Defender Firewall。

若規則不存在，建立：

```text
Name: Screenshot Server
Direction: Inbound
Protocol: TCP
Local Port: 55550
Action: Allow
```

不限制來源 IP。

### Client

不主動建立 Inbound rule。

## 24. Installer / Uninstaller

### Client installer

安裝時要求：

- Server IPv4

Port 固定 55550。

自動：

- 安裝程式
- 建立 client config
- 建立 Task Scheduler logon task
- 建立 Windows uninstall information

### Server installer

安裝時要求：

- Storage Root

自動：

- 安裝程式
- 建立 server config
- 建立 Firewall rule
- 建立 Windows uninstall information

### Uninstall

Client：

- 移除 Client 程式
- 移除 Task Scheduler task
- 本機 Cache 預設不要在無提示情況下刪除；可在解除安裝流程提供刪除選項

Server：

- 移除 Server 程式
- 移除 Firewall rule
- Server Screenshot data 預設不要因解除安裝而直接刪除

## 25. MVP non-goals

- Multi-client management UI
- Client registration
- Authentication token management
- Tor
- SOCKS
- .onion
- Web gallery
- Web thumbnail page
- Web login
- ZIP download
- AI analysis
- Keyboard logging
- Mouse logging
- Application tracking
- Screen streaming
- Multi-monitor
- SQLite
- Advanced cache ACL

## 26. Priority order

```text
P1  Screenshot
P2  Grayscale / JPEG
P3  HTTP upload / HTTP 200 ACK / 5 sec timeout
P4  Local Cache / recovery / duplicate handling
P5  Lock / sleep / unlock / wake
P6  Server config / Last Known Good Config
P7  Retention check + manual confirmation
P8  Installer / Task Scheduler / Firewall / Uninstaller
```
