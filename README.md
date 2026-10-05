# Windows Screenshot Monitor

家庭內由管理者授權的 Windows 電腦，定時截主螢幕，壓成灰階 JPEG，經區域網路送到同一台 Windows Server，再用檔案總管依時間查看。

這不是企業監控平台，也不是 Tor 隱藏服務。舊的首頁介紹來自上游 [TorCap](https://github.com/ciscoAnass/torcap)，只保留為改造前的參考。

> 只部署在你有權管理、且已獲授權的 Windows 系統。程式可以背景執行，但不做程序隱藏、rootkit、繞過安全軟體或其他規避技術。

## 先看哪一個分支

| 分支 | 這裡有什麼 | 什麼時候看 |
| --- | --- | --- |
| `main`（目前的預設分支） | 從 TorCap 匯入的舊程式，加上開工時的規格文件 | 要對照「改造前長什麼樣」時 |
| [`mvp-v1`](https://github.com/linhowja/windows-screenshot-monitor/tree/mvp-v1) | 目前的 Client / Server、安裝程式與已更新的說明 | 要看現在的系統時 |

GitHub 開啟專案頁時會先顯示 `main`。實作與最新說明請切到 `mvp-v1`。這裡的 `docs/` 仍是開工前版本，不要當成現況。

## 它做什麼

```text
Windows Client
  使用者已登入、桌面可用、未鎖定、未睡眠
    -> 只截 Primary Monitor
    -> 8-bit 灰階 JPEG
    -> HTTP POST /api/upload
    -> Windows Server TCP 55550
    -> 寫入確認後才回 HTTP 200
    -> 用檔案總管查看
```

正常上傳成功後，Client 不保留這張圖。只有上傳失敗才進入本機 Cache，之後再補傳。

資料夾依電腦與 Windows 帳號自動命名，不用手動填 Client ID：

```text
<StorageRoot>\
└── Hostname_WindowsUsername\
    └── YYYYMMDD\
        └── YYYYMMDD_HHMMSS_CC.jpg
```

例如 `JA-PC_howja\20261005\20261005_153012_37.jpg`。`CC` 是百分之一秒，不是序號。

## 它不做什麼

- 不做 Web 相簿、登入頁、即時串流、ZIP 下載
- 不做 Tor、SOCKS、`.onion`
- 不做鍵盤、滑鼠、程式使用記錄或 AI 行為分析
- 不做多螢幕、Client 註冊、密碼或 token
- 不做 SQLite；待上傳隊列就是 Cache 資料夾裡的檔案

## 規格與進度

現行說明在 [`mvp-v1`](https://github.com/linhowja/windows-screenshot-monitor/tree/mvp-v1)。Phase 1–7 已通過 Windows 實機驗證，記錄在 [`docs/05_PHASE_HISTORY.md`](https://github.com/linhowja/windows-screenshot-monitor/blob/mvp-v1/docs/05_PHASE_HISTORY.md)。尚未發 release tag。五分鐘 Cache 補傳的實地觀察仍待確認。

## 建議閱讀順序

請讀 `mvp-v1` 上的文件，不要讀本分支的舊 `docs/`：

1. [README](https://github.com/linhowja/windows-screenshot-monitor/blob/mvp-v1/README.md)
2. [docs/01_MVP_SPEC.md](https://github.com/linhowja/windows-screenshot-monitor/blob/mvp-v1/docs/01_MVP_SPEC.md)
3. [docs/00_PROJECT_OVERVIEW.md](https://github.com/linhowja/windows-screenshot-monitor/blob/mvp-v1/docs/00_PROJECT_OVERVIEW.md)
4. [docs/05_PHASE_HISTORY.md](https://github.com/linhowja/windows-screenshot-monitor/blob/mvp-v1/docs/05_PHASE_HISTORY.md)

## 授權

MIT。程式起點為 [ciscoAnass/torcap](https://github.com/ciscoAnass/torcap)。
