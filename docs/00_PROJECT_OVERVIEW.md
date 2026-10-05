# Windows Screenshot Monitor — Project Overview

更新：2026-10-06。這份文件保留專案定位，並補上目前實作狀態。功能仍以 `docs/01_MVP_SPEC.md` 為準；除錯細節看 `docs/05_PHASE_HISTORY.md`。

## 1. Project purpose

建立一套簡單的 Windows 64-bit Client + Windows 64-bit Server 截圖系統，主要用於家庭內由管理者授權的 Windows 電腦。

核心用途：定時擷取 Primary Monitor 畫面，壓成 8-bit 灰階 JPEG 後傳到 Windows Server，直接用 Windows File Explorer 查看圖片，以便依時間序列了解電腦使用情況。

本專案不是要做企業級監控平台，也不做 Web Gallery、即時串流、鍵盤滑鼠記錄或 AI 行為分析。

本系統只應部署在使用者有權管理、且有適當授權的 Windows 系統上。程式可以在背景執行，但不實作 rootkit、程序隱藏、繞過安全軟體或其他規避管理的 stealth 技術。

## 2. Current status

實作分支是 `mvp-v1`。`main` 仍是從 TorCap 匯入的基準加上規格文件，不是目前程式。

Phase 1–7 已完成，並於 2026-10-05 通過 Windows 安裝與 Client → Server 部署驗證。尚未發 release tag。Cache 每 5 分鐘補傳的實地觀察仍待確認；短於 5 分鐘的觀察不能直接判定補傳失敗。

已經定案、不要再按開工文件猜的點：

- 影像保留 Primary Monitor 原始解析度，不再縮成 25% × 25%。檔案大小靠灰階與 JPEG quality（預設 40）。
- 新 Server 是 `server.py`，不是把 `tor_server.py` 改大。`tor_server.py` 只是舊參考。
- 監聽固定 TCP 55550，不是設定項。
- Server 圖片不背景自動刪除；每個本機日期第一次啟動時詢問，確認後才刪本次候選。
- 安裝器是 Inno Setup，不是 `install.bat`。程式進 `C:\Program Files\Windows Screenshot Monitor\Client` 與 `Server`。
- Client 設定與 Cache 在 `C:\ProgramData\ScreenshotClient`。Server 設定在 `C:\ProgramData\ScreenshotServer`。
- 日誌在目前使用者的 `Documents\ScreenshotClient\Logs` 與 `Documents\ScreenshotServer\Logs`，每次啟動一個檔。
- HTTP runtime 依賴是 Flask app 加 Waitress，不使用 Flask development server 當正式服務。

仍未做：Server 設定 GUI、Client 身分驗證、TLS、多 Client 管理介面。

## 3. Current files

```text
app.py                         Client
server.py                      Server。現在要跑這個
windows_events.py              登入、鎖定、睡眠、喚醒
packaging/                     PyInstaller 與 Inno Setup
server_config.json             開發用 Server 預設
requirements.txt               mss, Pillow, requests, flask, waitress
docs/01_MVP_SPEC.md            規格
docs/05_PHASE_HISTORY.md       實作與除錯紀錄

tor_server.py                  舊 TorCap，不要啟動
install.bat                    舊 TorCap 安裝腳本，不要執行
config.json                    舊 TorCap 範本，現在 Client 不讀它
power_*_diagnostic.py          Phase 4 實機診斷，不是正式程式
```

## 4. AI roles

ChatGPT：需求、架構、規格與衝突裁決。不直接改 repository。

Grok：讀 repository、依規格實作、建 branch、commit、執行測試。是主要施工者。

Gemini：只做 code review，不與 Grok 同時修改同一個檔案。

## 5. Git workflow

實際使用：

```text
main          匯入基準與規格，保持可回復
mvp-v1        Phase 1–7 實作
```

沒有另開 `phase1-capture` 等分支。一次一個 Phase，小步驟 commit。有爭議時回到 SPEC。

## 6. Source project

起點：https://github.com/ciscoAnass/torcap

只借用截圖、HTTP 上傳與失敗後重試的概念。Tor、`.onion`、Web 相簿與 Web 登入不是本專案功能。

## 7. Golden rule

不要讓 AI 自行擴張需求。

```text
docs/01_MVP_SPEC.md > 目前程式與實機紀錄 > AI 猜測 > 舊 TorCap 行為
```

若 SPEC 沒有定義，先提出技術問題，由 ChatGPT 裁決後再改程式。
