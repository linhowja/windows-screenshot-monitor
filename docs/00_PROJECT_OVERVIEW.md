Windows Screenshot Monitor — Project Overview
1. Project purpose
建立一套簡單的 Windows 64-bit Client + Windows 64-bit Server 截圖系統，主要用於家庭內由管理者控制的 Windows 電腦。
核心用途：定時擷取 Primary Monitor 畫面，壓縮後傳送到 Windows Server，直接用 Windows File Explorer 查看圖片，以便依時間序列了解電腦使用情況。
本專案不是要做企業級監控平台，也不需要 Web Gallery、即時串流、鍵盤滑鼠記錄或 AI 行為分析。
本系統只應部署在使用者有權管理、且有適當授權的 Windows 系統上。程式可以在背景執行，但不實作 rootkit、程序隱藏、繞過安全軟體或其他規避管理的 stealth 技術。
2. AI roles
ChatGPT
角色：
需求分析
系統架構
規格整理
技術取捨
衝突裁決
Review Grok / Gemini 的提案
維持 Single Source of Truth
ChatGPT 不直接負責 repository coding。
Grok
角色：
讀取 GitHub repository
理解現有 TorCap 程式
依 SPEC 實作
建立 branch
commit
PR
執行程式與測試
Grok 是主要施工者。
Gemini
角色：
只做 code review
找 bug
找 Windows 相容性問題
找架構問題
對照 SPEC.md 驗證實作
Gemini 不與 Grok 同時修改同一個檔案。
3. Git workflow
建議：
```text
main
└── mvp-v1
```
或直接以功能 branch 從 main 開出，例如：
```text
main
├── phase1-capture
├── phase2-upload
├── phase3-cache
├── phase4-session-power
└── phase5-installer
```
原則：
main 保持可回復狀態。
Grok 一次處理一個 Phase。
Gemini review 某個明確 commit / PR，不直接修改。
有爭議時回到 SPEC，由 ChatGPT 裁決。
4. Source project
本專案以以下公開 GitHub 專案為主要參考與 code base：
Repository: https://github.com/ciscoAnass/torcap
Branch reviewed: main
目前 main 分支主要檔案：
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
5. Golden rule
不要讓 AI 自行擴張需求。
所有實作都必須以 `01_MVP_SPEC.md` 為準。若程式碼、AI 建議與規格衝突：
```text
SPEC.md > AI 猜測 > 舊 TorCap 行為
```
若 SPEC 沒有定義，先提出技術問題，由 ChatGPT 裁決後再改程式。
