# 實機除錯紀錄 — 2026-11-24（v1.2）

> 環境：Client `DESKTOP-AONEHQP`（172.16.0.115），Server `172.16.0.200`，埠 55550。  
> 安裝檔：`ScreenshotClientSetup-1.2.exe` / `ScreenshotServerSetup-1.2.exe`。

## 現象

Client 安裝後重新開機，Server 沒有收到任何訊號（無圖片、無開機紀錄）。

## 查到的原因

1. **安裝腳本中途中斷。**  
   `%TEMP%\ScreenshotClient-install.log` 只寫到：
   ```text
   [2026-11-24 14:34:57] Starting cleanup of previous client versions
   ```
   之後沒有「Wrote install_config」或「Scheduled task verified」。

2. **`install_config.json` 不存在。**  
   路徑 `C:\ProgramData\Microsoft\Windows\RuntimeHost\install_config.json` 沒有檔案。  
   Client 因此使用預設 `127.0.0.1`，不會連到 172.16.0.200。

3. **工作排程器任務沒建立。**  
   `schtasks /Query /TN "Runtime Host"` 回「系統找不到指定的檔案」。  
   當時在跑的兩個 `RuntimeHost.exe` 是手動啟動的。

4. **Server 防火牆原本沒有 55550 入站規則。**  
   後來手動新增規則後，`Test-NetConnection` 才通。

5. **開機失敗有留下紀錄。**  
   `C:\ProgramData\ScreenshotClient\boot_failed\boot_20261124_145506.txt`  
   內容為 `error=boot signal not delivered`。補上正確 IP 並重啟後，此紀錄補傳到 Server 當天資料夾，檔名 `boot_20261124_145506_offline.txt`。

## 網路與程序確認（當時有效的指令）

在 Client：

```powershell
Test-NetConnection -ComputerName 172.16.0.200 -Port 55550
Get-Process RuntimeHost -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='RuntimeHost.exe'" | Select-Object ProcessId, ExecutablePath
Get-Content "C:\ProgramData\Microsoft\Windows\RuntimeHost\install_config.json"
Get-ChildItem "C:\ProgramData\ScreenshotClient" -Force
Get-ChildItem "$env:USERPROFILE\Documents\ScreenshotClient\Logs" | Sort-Object LastWriteTime -Descending | Select-Object -First 5
```

在 Server：

```powershell
Get-NetTCPConnection -LocalPort 55550 -ErrorAction SilentlyContinue
Get-Content "C:\ProgramData\ScreenshotServer\server_config.json"
Get-ChildItem "D:\ScreenshotServer" -Directory
Get-ChildItem "D:\ScreenshotServer\*\20261124" -Filter "boot_*.txt" -Recurse
```

防火牆（Server，管理員）：

```powershell
New-NetFirewallRule -DisplayName "Screenshot Server 55550" -Direction Inbound -Protocol TCP -LocalPort 55550 -Action Allow
```

## 當場修復

1. 手動寫入 Client 的 `install_config.json`：

```json
{
  "server_ip": "172.16.0.200",
  "server_port": 55550
}
```

2. 結束舊程序後重新啟動 `RuntimeHost.exe`。  
   日誌出現大量 `Recovery upload success`，快取圖片上傳成功。

3. 手動建立工作排程器任務「Runtime Host」（登入時啟動）。

4. Server 收到：
   - 當天照片
   - `boot_20261124_150108.txt`（即時開機訊號）
   - `boot_20261124_145506_offline.txt`（離線補傳）

## 路徑對照（這次實機）

| 用途 | 路徑 |
|------|------|
| Client 程式 | `C:\ProgramData\Microsoft\Windows\RuntimeHost\RuntimeHost.exe` |
| Client Server IP | `C:\ProgramData\Microsoft\Windows\RuntimeHost\install_config.json` |
| Client 動態設定 | `C:\ProgramData\ScreenshotClient\runtime_state.json` |
| Client 開機失敗暫存 | `C:\ProgramData\ScreenshotClient\boot_failed\` |
| Client 日誌 | `文件\ScreenshotClient\Logs\` |
| Server 全域設定 | `C:\ProgramData\ScreenshotServer\server_config.json` |
| Server 每客戶端設定 | `C:\ProgramData\ScreenshotServer\clients\<Hostname_Username>\config.json` |
| Server 圖片與開機紀錄 | `D:\ScreenshotServer\<Hostname_Username>\YYYYMMDD\` |

這次客戶端身分：`DESKTOP-AONEHQP_linhowja`。

## 改間隔

- 全域 `server_config.json` 的 `screenshot_interval` 只影響之後新連上的客戶端。
- 已連上的客戶端要改秒數，改 Server 上的：
  `C:\ProgramData\ScreenshotServer\clients\DESKTOP-AONEHQP_linhowja\config.json`
- Client 下次成功上傳會套用。Client 本機的 `runtime_state.json` 改了也會被 Server 推送蓋掉。
- Server 設定視窗（Screenshot Server Configuration）目前只改全域，不改每客戶端檔。

## 下一版安裝要求

Client 安裝精靈在完成前必須確認能連上所填 Server 的 TCP 55550。連不上不得進入下一步。  
個人使用預設 Server IP：`172.16.0.200`。
