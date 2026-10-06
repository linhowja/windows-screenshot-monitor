# TorCap → Windows Screenshot Monitor

更新：2026-10-06。上半是實際結果；下半保留開工前的修改計畫，不要把計畫當成現況。

## 實際結果

| 檔案 | 結果 |
| --- | --- |
| `app.py` | 已改成 Client。不再走 Tor、不再縮 25%。 |
| `server.py` | 新增。這才是 Windows Server。 |
| `server_config_gui.py` | Phase 8-A 新增。本機設定視窗，不是 Web UI。 |
| `windows_events.py` | 新增。處理登入、鎖定、睡眠、喚醒。 |
| `packaging/` | 新增。PyInstaller 與 Inno Setup。 |
| `server_config.json` | 已改成 storage root、interval、quality、cache days、retention days。沒有 port 欄位。 |
| `requirements.txt` | 已改成 `mss`、`Pillow`、`requests`、`flask`、`waitress`。 |
| `README.md` | 已改寫成本專案介紹。 |
| `tor_server.py` | 保留舊檔，沒有當成新 Server。不要啟動。 |
| `install.bat` | 仍是舊 TorCap 腳本，會安裝到 `C:\MSOCache`。不要執行。 |
| `config.json` | 仍是舊 TorCap 範本，內有 `.onion` 與舊上傳密碼欄位。現在 Client 不讀它。 |
| `power_*_diagnostic.py` | Phase 4 診斷工具，不是正式程式。 |

正式安裝請用 `packaging/`，步驟見 `packaging/BUILD.txt`。

## 開工前計畫（歷史，不要當現況）

Source repository：https://github.com/ciscoAnass/torcap

當初準備改的檔案：

```text
.gitignore
LICENSE
README.md
app.py
config.json
install.bat
requirements.txt
server_config.json
tor_server.py
```

當初決定與後來不同的地方：

- 計畫要把 `tor_server.py` 大改。實作改新建 `server.py`，避免舊 Web 相簿變成更大的泥球。
- 計畫要求 25% × 25% 縮圖。Windows 實機發現文字過小，SPEC 已改為保留原始解析度。
- 計畫把 port 放進 `server_config.json`。實作固定 55550。
- 計畫可能改寫 `install.bat`。實作改用 Inno Setup，舊腳本未刪，但不得使用。
- 計畫要求改寫根目錄 `config.json`。實作的 Last Known Good 在 `C:\ProgramData\ScreenshotClient\config.json`，根目錄那份尚未清掉。

其餘原計畫仍有效：保留 MIT、移除 Tor / Web Gallery / 上傳密碼、不做 Client 註冊資料庫、不用 SQLite。
