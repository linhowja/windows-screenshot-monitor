# Project Handoff

更新：2026-10-06。這份文件原本是開工前的未決事項與第一輪指令。下面先寫現在已經定案的結果，再保留仍未做的項目。不要再按「第一輪只能分析、不能改程式」執行。

## 已經定案

| 原本未決 | 現在 |
| --- | --- |
| HTTP runtime | Flask app，正式監聽用 Waitress。不依賴 Flask development server。 |
| 安裝技術 | Inno Setup。x64。程式進 Program Files。 |
| Cache 位置 | `C:\ProgramData\ScreenshotClient\Cache\`。仍不做特殊 ACL。 |
| 設定同步 | 成功上傳的 HTTP 200 帶回最新 Client 設定。沒有單獨的 config-only API。 |
| 日誌 | 目前使用者 Documents，每次啟動一個檔。解除安裝不刪。 |
| 重複檔名 | 同一身分、日期、檔名已存在就回 HTTP 200，不覆蓋、不加序號。 |
| Server GUI | 仍未做。不要補做 Web UI。 |

## 仍未做，不要當成已經納入 MVP

- Server 本機設定 GUI。目前改設定仍是改 `server_config.json`。
- Client registration、token、密碼、TLS、來源 IP 限制、多 Client 管理介面。
- Cache 特殊 ACL。
- release tag。
- 5 分鐘 Cache 補傳的實地觀察。程式已有 300 秒週期，但這項現場觀察仍是 PENDING。

## 現在怎麼接手

1. 讀 `README.md`。
2. 讀 `docs/01_MVP_SPEC.md`。
3. 要除錯再讀 `docs/05_PHASE_HISTORY.md`。
4. 跑 Client 用 `app.py`，跑 Server 用 `server.py`。
5. 安裝用 `packaging/`，不要跑 `install.bat`，也不要跑 `tor_server.py`。

舊的第一輪「只做分析、不要 commit」指令已完成任務，不再貼在這裡。新工作仍要一次一個 Phase，不要因未定案功能自行加進來。
