# Windows Screenshot Monitor — Phase History

## Purpose

這份文件是 Development History / Decision / Debugging Record，不是目前規格。

目前規格仍以 `docs/01_MVP_SPEC.md` 為最高優先。若本文件與 SPEC 衝突，以 SPEC 與目前程式為準。

它保存每個 Phase 做了什麼、為什麼這樣設計、中間遇到的重要問題、如何修正、哪些問題只有 Windows 實機才發現，以及最後形成的設計。未來除錯時可以先看這裡，不必先翻完整個 Git history。

本文件整理時的實作基準是 `mvp-v1` 的 `668d16bb239cd11e0eb4ad0ce99c29adc03b1366`。本文件本身是之後的 docs-only commit。

---

## Overall Phase Status

| Phase | Scope | Status | Important Final Commit | Windows Verification |
| --- | --- | --- | --- | --- |
| Phase 1 | Screenshot / Image pipeline | PASS | `d24774ef6d77cd7db95402bd494f20f44d626df3` | PASS |
| Phase 2 | HTTP Upload / Server | PASS | `21d72d4d9cd8` | PASS |
| Phase 3 | Cache / Recovery | PASS | `470a805dff54` | PASS |
| Phase 4 | Lock / Sleep / Wake | PASS | `9b113899332c8a283d18e554b28f0bd77adb2c38` | PASS |
| Phase 5 | Configuration / LKG | PASS | `2e68abff06d8c4dd78b18593e9a606f7611dca3f` | PASS |
| Phase 6 | Retention check + manual confirmation | PASS | `668d16bb239cd11e0eb4ad0ce99c29adc03b1366` | PASS |
| Phase 7 | Installer / Deployment | PASS | `06c9cf6acc14bd02a3da066a9b0d6608f92c0325` | PASS |

Phase 7 的 installer / deployment 與 Windows Client → Server 整合已通過。Server GUI、authentication、TLS 與 multi-client management 仍未實作。Cache 的 5 分鐘實地補傳觀察仍是 PENDING FIELD TEST。

---

# Phase 1 — Screenshot / Image Pipeline

## Original goal

Client 只抓 Primary Monitor，轉成 8-bit grayscale JPEG，檔名帶 centisecond。成功產生的圖片留在記憶體，不寫永久本機檔。

## Implementation

- `mss.MSS().primary_monitor` 抓主螢幕。`monitors[0]` 是虛擬桌面，不用它。
- 轉成 Pillow `L` mode。
- JPEG quality 預設 40。
- 檔名：`YYYYMMDD_HHMMSS_CC.jpg`。`CC` 是百分之一秒，不是序號。
- 正常啟動不留下成功截圖。測試輸出只存在明確的 test mode。

## Important decisions

最初管線是：

```text
Capture → resize 25% × 25% → grayscale → JPEG
```

1920×1080 會變成 480×270，總像素只剩約 6.25%，文字與細節過小。

後來正式改成：

```text
Capture → original resolution → grayscale → JPEG
```

檔案大小只靠 8-bit grayscale 與 JPEG quality 40 降低，不再縮解析度。這是重要設計變更。

## Bugs discovered

沒有阻止 Phase 1 結案的功能錯誤。MSS 的 `mss.mss()` 已 deprecated，留到後續改成 `mss.MSS()`。檔名時間戳目前取在處理前，沒有改成 capture 完成後。

## Fixes

`ddd9cb2fe18d` 移除截圖 resize。`d24774ef` 同步 SPEC，拿掉 480×270 與 6.25% 的舊說明。

## Windows-specific issues

Linux self-test 不能代替實機。Windows 實機確認主螢幕 1920×1080 輸出仍是 1920×1080、JPEG、mode=`L`，且不含第二螢幕。

## Tests

`python app.py --self-test` 檢查檔名、JPEG、mode=`L` 與原始尺寸。

## Final status

PASS。

## Important commits

- `cf595f1529433d23c0534e8cf4d46e541e85a208`：Phase 1 初版，改 `app.py`、`requirements.txt`。
- `ddd9cb2fe18d`：取消 25% resize，保留原始解析度。
- `d24774ef6d77cd7db95402bd494f20f44d626df3`：SPEC 改為 keep original resolution。

---

# Phase 2 — HTTP Upload

## Original goal

Client 把記憶體中的 JPEG 用 HTTP POST 送到 Windows Server。Server 寫完並驗證後才回 HTTP 200。

## Implementation

- 新檔 `server.py`。舊 `tor_server.py` 保留，不作為新 Server。
- `POST /api/upload`，`multipart/form-data`。
- 欄位只有 `hostname`、`username`、`file`。
- 監聽 `0.0.0.0:55550`。Port 不是設定項。
- Client timeout 固定 5 秒。
- HTTP 200 才算成功。失敗先丟棄，Phase 3 才進 Cache。
- Server 用 Pillow 確認是可解碼 JPEG。
- 檔名日期用 `datetime` 驗證，拒絕 `20260231`。
- 同名檔已存在就回 200，不覆寫、不產生第二份。
- 路徑限制在 Storage Root 內，避免 path traversal。

## Important decisions

ACK 必須在完整寫入、關閉與大小確認之後。Duplicate 以檔名與身份視為成功，不做 image hash。

## Bugs discovered

Windows 實機所有 upload 回 HTTP 500，訊息是 `store verification failed`。Linux self-test 沒有抓到。

原因是 Windows 的 `os.open()` 未加 `O_BINARY` 時，JPEG 可能被當成文字模式寫入，`\n` 被翻譯，檔案大小與 bytes 不再等於 payload。Server 驗證失敗後刪除目的檔。

## Fixes

Server 與 Client Cache 都使用：

```text
binary_flag = getattr(os, "O_BINARY", 0)
```

寫入仍保持 exclusive create、完整寫入與 `fsync`。

## Windows-specific issues

這是 Windows text-mode I/O 問題。修正後 Windows 實機 upload 可以保存與 payload 相同的 JPEG。

## Tests

`python server.py --self-test` 覆蓋成功上傳、duplicate、非法 JPEG、非法日期、部分寫入不留檔，以及 55550 固定。

## Final status

PASS。

## Important commits

- `a28303a65d28`：Phase 2 初版，新增 `server.py`。
- `ad4d3fb932c5`：移除可設定 port，加入 JPEG decode、真實日期與完整寫入。
- `ae92c2a5108d`：Server 以 binary mode 修正 Windows 500。
- `21d72d4d9cd8`：Client Cache 同樣使用 binary mode。

---

# Phase 3 — Local Cache / Recovery

## Original goal

Upload 成功就丟棄記憶體 JPEG。Upload 失敗寫入 Local Cache，背景補傳，不阻塞截圖。

## Implementation

- Cache root：`C:\ProgramData\ScreenshotClient\Cache\YYYYMMDD\`。
- Cache 保存原本要上傳的 JPEG bytes，不重新編碼。
- 寫入使用 `.tmp`、完整寫入、`fsync`、`os.replace()`。
- Recovery worker 每 300 秒掃描，最舊到最新，成功後立即刪除。
- 單一檔案失敗不中斷後續 pending files。
- 同一時間只有一個 recovery worker。
- `.tmp` 不當成待上傳 JPEG。
- Cache retention 預設 3 天，依檔名時間，不用 mtime。
- Phase 3 提供 recovery trigger，但還不自行判斷 Windows Unlock/Wake。

## Important decisions

不用 SQLite。有檔案就代表待上傳，檔案系統本身就是 queue。成功上傳不落永久本機截圖；失敗才把原始 JPEG 寫入 Cache。

## Bugs discovered

初版 recovery 遇到單張失敗會 `break`，後面的 pending files 不會再試。Concurrency test 原本只證明 cache 寫入可並行，沒有證明正常 capture cycle 不被 recovery lock 擋住。

## Fixes

`470a805dff54` 改成單張失敗保留該檔，繼續嘗試後續檔案。補上 recovery worker 與 `handle_capture()` 並行的測試。

## Windows-specific issues

Cache binary write 的 Windows 修正在 Phase 2 的 `21d72d4d9cd8`。Phase 3 的 queue、retention 與 recovery 之後在 Windows 實機與後續 Phase 一起使用。

## Tests

Cache self-test 覆蓋成功不留檔、失敗進 Cache、順序、Server 恢復後清空、Server 仍不可用時保留、duplicate recovery、`.tmp` 忽略與 3 天 retention。

## Final status

PASS。

## Important commits

- `24b6267ba77a`、`368c9708c925`、`5c7d54ad4328`：Phase 3 cache 與 recovery。
- `470a805dff54`：單張失敗後繼續，並補強 concurrency test。

---

# Phase 4 — Windows Session / Power

## Original goal

只有使用者已登入、互動桌面可用、未鎖定且系統未睡眠時才截圖。Lock、Logoff、Sleep 停止截圖。Unlock 與 Wake 不立即補拍，先觸發 recovery，下一張等完整 interval。

## Implementation

- Session 使用 hidden message window 與 `WTSRegisterSessionNotification`。
- 處理 logon、logoff、lock、unlock。
- `capture_enabled = logged_on AND session_unlocked AND desktop_ready AND system_awake`。
- 只有一個 recovery worker。事件只喚醒現有 worker。
- Power callback 只更新 state，不做網路、截圖或長時間工作。
- 註冊失敗記錄 Windows error，capture 維持 disabled，不 crash。

## Important decisions

需要 HWND 時只建立 hidden message window，不是使用者介面，也不是程序隱藏功能。

## Bugs discovered

Unlock 後 Windows 11 不一定再送 `WTS_SESSION_DESKTOP_READY`。初版因此把 `desktop_ready` 留在 false，recovery 要等 300 秒週期。Startup 也曾連續觸發兩次 recovery。

Power 路徑最初使用 `RegisterSuspendResumeNotification` 與 `WM_POWERBROADCAST`。Windows 實機 `powercfg /a` 顯示 S3，System Event 42 與 wake Event 1 也確認睡眠與喚醒，但 hidden window 收不到 `WM_POWERBROADCAST`。

## Fixes

Unlock 後改做有限的 desktop readiness 確認，不再永久等待 `WTS_SESSION_DESKTOP_READY`。確認後立即 recovery，不立即截圖。Startup recovery 只跑一次。

獨立診斷確認 callback API 可用後，正式改為 `PowerRegisterSuspendResumeNotification` 加 `DEVICE_NOTIFY_CALLBACK`。實機收到：

- Type 4 `PBT_APMSUSPEND`
- Type 7 `PBT_APMRESUMESUSPEND`
- Type 18 `PBT_APMRESUMEAUTOMATIC`

Type 7 與 Type 18 可能各記一次 resume log，但沒有造成重複截圖或第二個 recovery worker，目前不特別修正。

## Windows-specific issues

Session 與 S3 都必須在 Windows 實機驗證。Linux 只保留 session state self-test；非 Windows 執行 Windows API self-test 會明確失敗，不假裝成功。

## Tests

Windows 實機確認 Lock/Unlock、S3 Sleep/Wake、wake while locked、Unlock 後 recovery，以及 Server 不可用時 Cache 保留。

## Final status

PASS。

## Important commits

- `f96687fdf651`：新增 `windows_events.py`。
- `43e6a3321919`：lock/sleep 停止截圖，只喚醒一個 recovery worker。
- `33bf078d2757`：補 64-bit ctypes signatures。
- `e3e386b999e6`：Windows API self-test 與手動測試說明。
- `98a9fa9216f0`：Unlock 後確認 desktop readiness。
- `7ce85324c3c2`：startup recovery 只執行一次。
- `1470fe5edaaaf00f903892ce9ffa1507d805b6f2`：window power diagnostic。
- `d47dd0683351`：callback diagnostic。
- `84e43602c74854804492b9d64ed436c211a613a3`：diagnostic 在非 Windows 可匯入。
- `9b113899332c8a283d18e554b28f0bd77adb2c38`：正式改用已驗證的 S3 callback。

---

# Phase 5 — Configuration / LKG / Runtime Sync

## Original goal

Server 設定持久化。Client 保存 Last Known Good。HTTP 200 同步有效設定。Server 離線時繼續用 LKG。

## Implementation

- `server_config.json`：`storage_root`、`screenshot_interval`、`jpeg_quality`、`client_cache_days`、`server_image_retention_days`。
- 預設是 `dev_storage`、20、40、3、14。
- 優先順序：explicit `--storage-root` > config file > default。
- Client LKG：`C:\ProgramData\ScreenshotClient\config.json`。
- HTTP 200 回 interval、quality、cache days。不回 storage root 或 server retention days。
- 非法或損壞設定不 crash，保留最後有效值。
- `server_image_retention_days` 在 Phase 5 只保存，不刪圖。

## Important decisions

沒有 config service、獨立 config API、資料庫或 GUI。設定只走 JSON 與 HTTP 200。

## Bugs discovered

1. `--server-ip` 的 parser default `127.0.0.1` 會在未指定時覆蓋 LKG。
2. Capture loop 可能沿用啟動參數，HTTP 200 更新不一定影響後續截圖。
3. HTTP 200 把 interval 從 20 改成 30 後，本輪剩餘等待仍用舊 interval。
4. PowerShell 5.1 `Set-Content -Encoding UTF8` 會寫 UTF-8 BOM。`encoding="utf-8"` 拋出 `Unexpected UTF-8 BOM`，Server 把有效的 30/50/5 誤判成損壞並退回 20/40/3。

## Fixes

未指定 `--server-ip` 使用 LKG；第一次沒有 LKG 才用 `127.0.0.1`。每個 capture/recovery cycle 讀 `effective_runtime()`。Capture 完成後重新讀 interval 再計算下一次等待。明確 CLI override 仍優先。

Server config 改用 `utf-8-sig` 讀取，BOM 與無 BOM 都接受。儲存仍寫無 BOM UTF-8。修正 commit 是 `2e68abff06d8c4dd78b18593e9a606f7611dca3f`。

## Windows-specific issues

Windows 實機確認 LKG 建立、HTTP 200 同步、interval 20 到 30、quality 40 到 50、cache days 3 到 5、Server 離線保留 LKG，以及恢復後實際使用 30 秒 interval。BOM 問題也是 Windows PowerShell 實機發現的。

## Tests

Linux config self-test 覆蓋 LKG、CLI override、非法 config、離線不重置，以及下一輪 interval。`python server.py --self-test` 可不帶 `--storage-root`。Windows 驗收另做實機同步。

## Final status

PASS。

## Important commits

- `524d1ff90135`：Server config 持久化。
- `09321d09f4aa`：Client LKG。
- `931f3d789fb6`：SPEC 同步。
- `8cd6fc447b1e`、`af2aa03da70a`：未指定 `--server-ip` 不覆蓋 LKG。
- `09d57f2109c4`：下一輪等待使用同步後的 interval。
- `51324f58f262`：追蹤中的 `server_config.json` 改成 Phase 5 格式。
- `2e68abff06d8c4dd78b18593e9a606f7611dca3f`：UTF-8 BOM 相容。

---

# Phase 6 — Retention check + manual confirmation

## Original goal

Server 圖片保留改成每日第一次啟動檢查，使用者確認後才刪除。不是背景自動 cleanup。

## Implementation

```text
Server startup
→ load config
→ retention check
→ Windows Yes / No
→ start HTTP server
```

- 每個本機日期只詢問一次。
- `server_retention_state.json` 與 `server_config.json` 同層，不放 Storage Root。
- 年齡用 filename timestamp，不用 filesystem mtime。
- 只有 `captured < now - retention_days` 才是 candidate。恰好 14 天保留；超過 14 天，例如 14 天又 1 小時，才是候選。
- 只處理 `<StorageRoot>\<Identity>\<YYYYMMDD>\<YYYYMMDD_HHMMSS_CC.jpg>`。
- `.tmp`、`.png`、壞檔名、壞日期、檔名日期與目錄不一致，以及非正式 hierarchy 不刪。
- Yes 只刪本次掃描清單，不重新掃描。
- No、關閉或無法取得選擇都保留。
- 單檔刪除失敗繼續處理其他候選。
- 掃描例外不刪檔，也不阻止 Server 聽 `0.0.0.0:55550`。

## Important decisions

檢查放在 HTTP listener 之前，避免刪除與新 upload 競爭，因此不做 active upload tracking。沒有每小時 cleanup thread。Identity 資料夾名稱不再額外驗證。

## Bugs discovered

`server_retention_state.json.tmp` 若在 `os.replace()` 前留下，下次 `O_EXCL` 可能失敗並擋住啟動。Storage 掃描的 `PermissionError` 或其他例外也不能讓 Retention 阻止 Server 啟動。

## Fixes

寫入新 state 前先移除殘留 `.tmp`，再寫暫存檔、`fsync`、`os.replace()`。正式 state 檔不會先被刪除。掃描失敗只記錄 `Retention check error`，不刪圖片，`main()` 繼續 listen。

## Windows-specific issues

確認視窗使用 Windows `MessageBoxW`，預設按鈕是 No。實機確認過期候選、Yes 刪除、No 保留、同一天跳過、跨日再檢查、損壞 state、殘留 `.tmp`、單檔刪除失敗、掃描失敗、14 天邊界，以及 Retention 問題後 Server 仍啟動。

## Tests

`python server.py --self-test` 覆蓋候選、邊界、非正式檔案、同日跳過、昨日重查、損壞 state、刪除失敗、殘留 `.tmp` 與掃描例外。

## Final status

PASS。

## Important commits

- `64503f328844de68fffcf265016408530054121d`：每日人工確認 retention。
- `e01886f2a507af38b993fc27d7471da4d34ca5b5`：SPEC 改成 manual confirmation。
- `668d16bb239cd11e0eb4ad0ce99c29adc03b1366`：殘留 `.tmp` 與掃描失敗不阻擋啟動。

---

# Phase 7 — Installer / Deployment

## Original goal

把 Phase 1～6 做成可在 Windows 10/11 64-bit 安裝與運作的 Client / Server。範圍包含 PyInstaller、Inno Setup、x64 installation、Program Files、ProgramData、Task Scheduler、Firewall、install manifest、uninstall、runtime logging、Storage Root，以及 Windows 實機部署驗證。

## Implementation

- `packaging/client.spec` 與 `packaging/server.spec` 產生 `ScreenshotClient.exe`、`ScreenshotServer.exe`。
- Spec 以 `SPECPATH` 的上一層找 repository root 的 `app.py` / `server.py`，不依賴目前工作目錄。
- Windows 本機已成功產生兩個 EXE。Client / Server self-test 成功；Server self-test ExitCode 為 0。
- Inno Setup 使用 `ArchitecturesAllowed=x64compatible` 與 `ArchitecturesInstallIn64BitMode=x64compatible`。`{autopf}` 因此進入 `C:\Program Files\Windows Screenshot Monitor\...`。
- Client ProgramData 是 `C:\ProgramData\ScreenshotClient`，放 config 與 Cache。不建立 Client inbound firewall rule。
- Server ProgramData 是 `C:\ProgramData\ScreenshotServer`，放 server config、retention state 與 install manifest。Storage Root 由安裝時選擇，並寫 ownership marker。
- Task 使用 `New-ScheduledTaskAction`、`New-ScheduledTaskTrigger -AtLogOn`、`New-ScheduledTaskPrincipal -GroupId S-1-5-32-545` 與 `Register-ScheduledTask`。Client 是 Limited，Server 是 Highest。安裝後用 `schtasks /Query` 驗證。
- Server firewall 名稱是 `Screenshot Server`，Inbound TCP 55550 Allow。已存在就不重複建立。
- 解除安裝當下才詢問是否刪 application data。Documents logs 不刪。Storage Root 只有在使用者選 Yes、manifest 證明安裝前不存在、ownership marker 存在，且重新掃描只含正式截圖階層時才整棵刪除。

## Bugs discovered

第一輪 Server installer 實機把程式裝到 `C:\Program Files (x86)\Windows Screenshot Monitor\Server`。原因是 Inno Setup 沒有明確使用 x64-compatible installation mode。同一輪 `Screenshot Server` task 沒有建立。原本的 GroupId 加 `InteractiveToken` XML 不可靠，而且 `schtasks /Create` 的失敗被隱藏，安裝看起來仍成功。這兩個問題都是 Windows 實機才發現的。

## Fixes

Client 與 Server 的 `.iss` 都加入 x64compatible 設定，沒有硬編碼 `C:\Program Files`。Task 改成 ScheduledTasks cmdlets。建立或 `schtasks /Query` 失敗時，installer script 寫 install log 並直接失敗。重新安裝會清掉先前誤裝的 `Program Files (x86)` 程式目錄，但不刪 ProgramData。

## Runtime logs

Log 使用 Windows Known Folder `Documents`，每次 process start 一個檔，不做 1 MB rotation。

```text
Documents\ScreenshotClient\Logs\YYYYMMDD_HHMMSS_CC.LOG
Documents\ScreenshotServer\Logs\YYYYMMDD_HHMMSS_CC.LOG
```

解除安裝即使選擇刪除 application data，也不刪這些 log。

## Windows verification

2026-10-05 Windows 實機：

- Client / Server installer 都是 x64。
- Server 安裝到 `C:\Program Files\Windows Screenshot Monitor\Server`，Program Files (x86) 不存在。
- Task `Screenshot Server` 建立成功並可實際執行。Server 啟動後聽 `0.0.0.0:55550`。
- Firewall `Screenshot Server` 為 Enabled / Inbound / Allow。
- Storage Root 是 `C:\ScreenshotServer-Test2`，`install_manifest.json` 正常。
- PyInstaller one-file 的父子 process 不是重複啟動問題。
- Client 安裝到 `C:\Program Files\Windows Screenshot Monitor\Client`。Task `Screenshot Client` 建立成功並可啟動。
- Hostname `JA-PC`，Windows username `howja`，Primary Monitor `1920x1080`，JPEG quality 40，interval 20 秒。
- Server 收到圖片，階層是 `C:\ScreenshotServer-Test2\JA-PC_howja\20261005\*.jpg`，連續多張，約每 20 秒一張。
- Client log 有 Capture、JPEG encode、HTTP 200、Uploaded discarded。Capture → JPEG → HTTP → Server → File Storage 整條成功。
- Server 中斷時 Client 不停止，失敗圖片寫入 `C:\ProgramData\ScreenshotClient\Cache\YYYYMMDD\`。Server 恢復後新截圖可以上傳。

Recovery worker 的設計週期是 300 秒。這次 Server 恢復後沒有立即補傳舊 Cache，等待時間不到 5 分鐘，不能直接判定為 Bug。5 分鐘實地補傳留待實際工作環境觀察。

## Final status

- Installer / deployment：PASS。
- Windows real-machine Client → Server integration：PASS。
- Cache offline storage：PASS。
- Recovery mechanism：已實作，既有 self-test 通過。
- Real-world 5-minute recovery observation：PENDING FIELD TEST。

目前已達到可以進入實際工作環境部署測試的程度。Server GUI、authentication、TLS 與 multi-client management 仍未做。

## Important commits

- `f0fad626b01af3331df089fe104aff59d40b227e`：正式路徑與檔案 log。
- `512ab4be085ce5edf13d929c5ff908e837de5b2e`：installer scripts。
- `7a0b449c4e287de9a4d3971b573c50350415d4af`：解除安裝當下才詢問刪資料。
- `caca7fe138efb2cfc6c6f6ad44954e874d67188f`：Storage Root ownership 檢查。
- `a7e562116738755913f9b182335b257f06be96d7`：Documents session log。
- `4c4490c508210dc586e9969cdc3dff8d2397ab2c`：PyInstaller spec 進入點。
- `06c9cf6acc14bd02a3da066a9b0d6608f92c0325`：x64 installer 與 Scheduled Task。

---

# Important Debugging Lessons

1. Linux self-test 不等於 Windows acceptance。
2. Windows binary I/O 必須加 `O_BINARY`。
3. Windows power event 不能只看 API 文件，S3 必須實機驗證。
4. CLI parser default 可能意外覆蓋 LKG。
5. Runtime configuration 必須區分啟動值與每個 cycle 的 effective runtime。
6. PowerShell UTF-8 BOM 會影響 JSON parser。
7. Retention 必須先建立 candidate list，再依使用者確認刪除。
8. 可選功能的 exception 不應阻塞核心 Server startup。
9. Atomic write 必須處理殘留 `.tmp`。
11. Inno Setup 必須明確使用 x64-compatible mode，否則 `{autopf}` 會進 Program Files (x86)。
12. Group task principal 不能再搭配 `InteractiveToken`；建立失敗必須讓 installer 失敗。
13. Recovery worker 週期是 300 秒。短於 5 分鐘的觀察不能直接判定補傳失敗。

---

# Current Project Status

```text
Current branch: mvp-v1

Phase 7 deployment HEAD:
06c9cf6acc14bd02a3da066a9b0d6608f92c0325

main:
b01213eee4902762badc848d5196745ef194af63

Phase 1-7 installer/deployment: completed
5-minute cache recovery field observation: pending
Release: not created
```
