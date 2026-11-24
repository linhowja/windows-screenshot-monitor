# Gemini Review Handoff — Windows Screenshot Monitor

> 日期：2026-11-24  
> 分支：`mvp-v1`  
> 基準 commit：`4b1ce5c430e79e41a164b09d1bd6565439646895`  
> 目的：請 Gemini 從頭到尾重新驗證目前程式是否有 bug、邏輯錯誤或與規格不符之處。

---

## 1. 請先讀這些

1. **`docs/FULL_SPECIFICATION.md`**  
   目前完整規格與實作現況。若與舊文件衝突，以這份與程式為準。

2. **`README.md`**  
   專案定位與快速概覽。

3. **`docs/01_MVP_SPEC.md`**  
   早期 MVP 規格。部分內容已過時（安裝路徑、每客戶端設定、鎖定行為等），僅作參考。

4. **`docs/05_PHASE_HISTORY.md`**  
   各階段實作與除錯紀錄。不是規格。

---

## 2. 角色與範圍

- 你是 **Reviewer**。請找出 bug、邏輯錯誤、邊界條件問題、與規格不符之處。
- 不要直接改程式、不要開 PR，除非明確被要求。
- 回報時請指出：檔案、函式、問題描述、可能影響、建議修正方向。

---

## 3. 近期重要變更（需重點驗證）

### 3.1 Client 安裝與隱藏（commit 約 `b16902b`、`ee60e16`）

- 主程式改名為 `RuntimeHost.exe`
- 安裝到 `C:\ProgramData\Microsoft\Windows\RuntimeHost\`
- 資料夾設隱藏 + 系統屬性
- 設定程式改名為 `RuntimeHostConfig.exe`，要求管理員（UAC）
- 工作排程名稱改為 `Runtime Host`，並限制一般使用者修改
- 安裝時自動清掉舊版（Program Files、舊工作名稱、舊 ProgramData、開始功能表）

相關檔案：

- `packaging/client.spec`
- `packaging/client_config.spec`
- `packaging/client.iss`
- `packaging/client_install.ps1`
- `packaging/client_uninstall.ps1`

### 3.2 成功連線後鎖定設定（commit 約 `4fb5f3b`）

- Client 第一次成功連上 Server（HTTP 200）後，`config.json` 的 `locked` 設為 `true`
- 鎖定後 `RuntimeHostConfig.exe` 拒絕開啟與儲存，顯示需解除安裝重裝的訊息
- Server 推送的間隔、品質、快取天數仍可由程式更新
- 要改設定必須解除安裝後重新安裝

相關檔案：

- `app.py`：`apply_server_config`、`_mark_settings_locked`、`upload_jpeg`、`load_client_config`
- `client_config_gui.py`：`is_settings_locked`、`run_gui`、`save_settings`

### 3.3 每客戶端獨立設定檔（commit 約 `838dc0e`）

- Server 為每台客戶端建立獨立設定：
  ```text
  C:\ProgramData\ScreenshotServer\clients\<Hostname_Username>\config.json
  ```
- 第一次成功上傳時，用全域 `server_config.json` 的預設值建立
- 之後回傳該客戶端自己的設定
- 改全域設定只影響之後新連上的客戶端

相關檔案：

- `server.py`：`client_config_path`、`load_or_create_client_config`、`success_response`、`api_upload`

### 3.4 Self-test 修正（commit `4b1ce5c`）

- `client_config_gui.py` 的 self-test 原本還檢查舊的 `ScreenshotClientConfig.exe` 名稱，已改為 `RuntimeHostConfig.exe`。

---

## 4. 請重點檢查的項目

### Client（`app.py`）

- [ ] `locked` 旗標在第一次 HTTP 200 後是否一定會設為 true（含 config 回應非 JSON 的情況）
- [ ] `apply_server_config` 在寫檔失敗時是否仍更新 runtime（目前設計是會更新）
- [ ] `load_client_config` 是否正確保留 `locked`
- [ ] Server 推送的設定是否不會覆蓋 `server_ip`
- [ ] Cache 寫入、補傳順序、過期刪除是否仍正確
- [ ] 啟動延遲 7–30 秒是否只發生一次

### Client 設定視窗（`client_config_gui.py`）

- [ ] 鎖定後是否真的拒絕開啟與儲存
- [ ] 未鎖定時儲存是否仍正常
- [ ] self-test 的打包名稱檢查是否與目前 `client.iss` / `client_config.spec` 一致

### Server（`server.py`）

- [ ] 每客戶端設定檔是否在第一次上傳時建立，之後是否讀取同一份
- [ ] 身分名稱 `Hostname_Username` 是否與儲存路徑一致
- [ ] 無效的每客戶端設定是否會退回全域預設
- [ ] 重複上傳是否仍回 HTTP 200 且不覆蓋
- [ ] 路徑穿越防護是否仍有效

### 安裝腳本

- [ ] `client_install.ps1` 清舊版後是否一定會寫入新的 `config.json`（含安裝時輸入的 Server IP）
- [ ] 權限設定是否讓 Client 程式能寫入設定，同時限制一般使用者修改工作排程
- [ ] 解除安裝是否能清掉目前與舊版路徑

### 規格一致性

- [ ] `docs/FULL_SPECIFICATION.md` 與程式行為是否一致
- [ ] 有沒有程式行為與文件描述衝突的地方

---

## 5. 已知設計決定（不是 bug）

- Client 不是 Windows Service。截圖需要使用者互動桌面，用工作排程器在登入時啟動是正確做法。
- 沒有從 Server 強迫更新 Client 執行檔的機制。目前只能推送設定。
- Server GUI（`ScreenshotServerConfig.exe`）只改全域 `server_config.json`。個別客戶端設定需直接編輯 `clients\<identity>\config.json`。
- `config.json` 給 Users 可寫，是為了讓 Client 程式能寫入鎖定旗標與 Last Known Good。直接用記事本改檔在技術上仍可能，但設定視窗已被鎖定擋下。
- 不實作 rootkit、程序隱藏、規避防毒。隱藏資料夾與中性名稱是為了降低一般使用者意外發現的機會，不是規避技術。

---

## 6. 如何驗證

在 Windows 上（或可執行的環境）：

```text
python app.py --self-test
python server.py --self-test
python client_config_gui.py --self-test
python server_config_gui.py --self-test
```

安裝與實機行為需要 Windows 環境：

- 用 Inno Setup 編譯 `packaging/client.iss` 與 `packaging/server.iss`
- 安裝後確認路徑、隱藏屬性、工作排程、權限
- 讓 Client 成功上傳一次，確認 `locked` 變 true，且設定視窗拒絕開啟
- 在 Server 上修改該客戶端的 `config.json`，確認下次上傳後 Client 套用新值

---

## 7. 不要動的東西

- `tor_server.py`、根目錄 `install.bat`、根目錄 `config.json` 是舊 TorCap 殘留，不要當成現況。
- 不要把程式改成 Windows Service。
- 不要加入身分驗證、TLS、Web UI，除非明確被要求。
- 預設分支是 `main`，實作在 `mvp-v1`。審查與修改請以 `mvp-v1` 為準。

---

## 8. 回報格式建議

請用以下格式回報發現：

```text
[嚴重程度] 檔案:函式
問題描述
可能影響
建議修正
```

嚴重程度：Critical / Major / Minor / Note

若沒有發現問題，請明確說明檢查過哪些檔案與項目，以及結論。
