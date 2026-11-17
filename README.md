# Windows Screenshot Monitor

家庭內由管理者授權的 Windows 10/11 64-bit 電腦，定時截主螢幕，壓成灰階 JPEG，經區域網路送到同一台 Windows Server，再用檔案總管依時間查看。

這不是企業監控平台。舊首頁介紹的 Tor、`.onion` 與 Web 相簿來自上游 [TorCap](https://github.com/ciscoAnass/torcap)，不再是這個專案的功能。

> 只部署在你有權管理、且已獲授權的 Windows 系統。程式可以背景執行，但不做程序隱藏、rootkit、繞過安全軟體或其他規避技術。

## 30 秒看懂

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

上傳失敗、逾時（5 秒）或 Server 沒回應時，圖片進入本機 Cache，Client 繼續截圖。約每 5 分鐘補傳一次；解鎖或喚醒且桌面可用後會再觸發一次。補傳由舊到新，成功一張就刪一張，不拋住下一次截圖。

Server 不提供網頁。圖片直接用檔案總管的大圖示或超大圖示查看。正式監聽用 Waitress，不是 Flask development server。

## 資料放在哪

安裝程式與圖片分開。Storage Root 在安裝 Server 時選擇，之後可改，但只影響新資料，不搬舊檔。

```text
<StorageRoot>\
└── Hostname_WindowsUsername\
    └── YYYYMMDD\
        └── YYYYMMDD_HHMMSS_CC.jpg
```

身分由電腦名稱與 Windows 帳號組成，例如 `JA-PC_howja`。檔名裡的 `CC` 是百分之一秒，不是序號。同一客戶、同一天、同一檔名再上傳時，Server 視為成功並回 HTTP 200，不覆蓋、也不另存一份。

## 設定從哪裡來

Server 是設定來源。預設為截圖間隔 20 秒、JPEG 品質 40、Client Cache 保留 3 天、Server 圖片保留 14 天。成功上傳的 HTTP 200 會順便回傳最新的 Client 設定。Server 離線時，Client 繼續用上一次成功的設定，不停止工作。

Server 圖片不會背景自動刪除。每個本機日期第一次啟動時檢查，確認後才刪除這次掃描到的候選。

## 現在做到哪

此分支是目前實作。Phase 1–7 已通過 Windows 實機驗證，細節在 [`docs/05_PHASE_HISTORY.md`](docs/05_PHASE_HISTORY.md)。Cache recovery 的 300 秒週期已完成實測：Server 中斷期間產生的 Cache 檔案，在週期觸發後由舊到新補傳，成功後刪除本機 Cache 檔案。Phase 8-A 加入本機 Server 設定 GUI，不是 Web UI。

| Phase | 範圍 | 狀態 |
| --- | --- | --- |
| 1 | 截圖與灰階 JPEG | 通過；後來改為保留原始解析度，不再縮成 25% |
| 2 | HTTP 上傳、寫入確認、5 秒逾時 | 通過 |
| 3 | 失敗進 Cache、補傳、重複上傳保護 | 通過；300 秒補傳已完成實測，由舊到新補傳，成功後刪除本機 Cache |
| 4 | 鎖定、睡眠、解鎖、喚醒 | 通過 |
| 5 | Server 設定與 Last Known Good | 通過 |
| 6 | 每日啟動時人工確認後才刪舊圖 | 通過 |
| 7 | 安裝、登入工作、防火牆、解除安裝 | 通過 Windows 部署驗證 |
| 8-A | Server 本機設定 GUI | 已實作；儲存後需重新啟動 Server |
| 8-B | Client 啟動後第一次截圖隨機延遲 | 已實作；只延遲一次 7–30 秒，之後恢復固定間隔 |

尚未做：身分驗證、TLS、多 Client 管理介面。尚未發 release tag。Server 設定 GUI 已於 Phase 8-A 實作，見下方啟動方式。

## 程式在哪

| 檔案 | 責任 |
| --- | --- |
| `app.py` | Windows Client：截圖、壓縮、上傳、Cache |
| `server.py` | Windows Server：接收上傳、寫檔、設定、保留檢查 |
| `server_config_gui.py` | Server 本機設定視窗。開發時執行這個；安裝後是 `ScreenshotServerConfig.exe` |
| `windows_events.py` | 登入、鎖定、睡眠與喚醒 |
| `packaging/` | PyInstaller 與 Inno Setup：`ScreenshotClient.exe`、`ScreenshotServer.exe` |
| `tor_server.py` | 舊 TorCap 伺服器，不要當成現在的 Server |
| `install.bat` | 舊 TorCap 安裝腳本，不要執行 |
| `config.json` | 舊 TorCap 範本，現在 Client 不讀它 |

安裝後的位置：

```text
C:\Program Files\Windows Screenshot Monitor\Client
C:\Program Files\Windows Screenshot Monitor\Server
C:\ProgramData\ScreenshotClient          設定與 Cache
C:\ProgramData\ScreenshotServer          設定、保留狀態、安裝清單
Documents\ScreenshotClient\Logs          每次啟動一個日誌
Documents\ScreenshotServer\Logs
```

Server 安裝時建立入站規則 `Screenshot Server`：TCP 55550 Allow。Client 不建入站規則。解除安裝預設不刪圖片與 Documents 日誌。

Server 設定 GUI 只改這 5 項：`storage_root`、`screenshot_interval`、`jpeg_quality`、`client_cache_days`、`server_image_retention_days`。設定檔是 `C:\ProgramData\ScreenshotServer\server_config.json`。Port `55550` 不能在 GUI 改。Save 寫入設定檔；正在跑的 Server 要重新啟動後才套用。啟動方式：

```text
python server_config_gui.py
C:\Program Files\Windows Screenshot Monitor\Server\ScreenshotServerConfig.exe
```

開始功能表也有 `Screenshot Server Configuration` 與 `Screenshot Client Configuration`。Close 不寫設定。Client 設定視窗寫入 `C:\ProgramData\ScreenshotClient\config.json`，可改 Server IPv4；間隔、品質與 Cache 天數在下次成功上傳後會被 Server 帶回的值覆寫。

Client 每次 process 啟動只抽一次 7–30 秒整數延遲，等完才做第一次截圖。之後恢復 `screenshot_interval`。這不是每次截圖都隨機，也不是 Server 設定，不影響 300 秒 Cache recovery。鎖定或睡眠期間仍不截圖。

建置說明見 [`packaging/BUILD.txt`](packaging/BUILD.txt)。

## 先讀哪份文件

1. [`docs/01_MVP_SPEC.md`](docs/01_MVP_SPEC.md)：功能規格。與程式衝突時以它為準。
2. [`docs/05_PHASE_HISTORY.md`](docs/05_PHASE_HISTORY.md)：每階段做了什麼、Windows 實機遇到什麼。它不是規格。
3. [`docs/00_PROJECT_OVERVIEW.md`](docs/00_PROJECT_OVERVIEW.md)：專案定位與目前狀態。
4. [`docs/02_TORCAP_FILE_MAP.md`](docs/02_TORCAP_FILE_MAP.md)：舊檔實際怎麼處理；下半是開工計畫，不要當現況。
5. [`docs/04_PROJECT_HANDOFF.md`](docs/04_PROJECT_HANDOFF.md)：已定案項目與仍未做的項目。不要再把它當成未決清單。

## 授權

MIT。程式起點為 [ciscoAnass/torcap](https://github.com/ciscoAnass/torcap)。
