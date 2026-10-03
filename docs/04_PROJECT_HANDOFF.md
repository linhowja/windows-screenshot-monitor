Project Handoff — Open Items / Grok First Prompt / New ChatGPT Project Start
這份文件整合原本的：
`04_OPEN_ITEMS.md`
`05_GROK_FIRST_PROMPT.md`
`06_CHATGPT_NEW_PROJECT_START.md`
用途：因 ChatGPT 免費方案的 Project knowledge 檔案數量限制，將「未決技術項目、Grok 第一輪指令、新 ChatGPT Project 開場方式」集中成單一文件。
---
Part A — Open Technical Decisions
這份區塊只放尚未正式定案的問題。
不要把這裡的內容當成已確定規格。
A1. HTTP server runtime
目前方向：保留 Flask API 概念。
尚未完全定案：
Flask development server
Waitress
其他 Windows-friendly WSGI/HTTP runtime
原則：正式使用不要依賴 Flask development server。
A2. Server local settings GUI
需求已確定需要本機設定功能，但尚未決定 GUI 技術：
Python GUI
packaged local configuration utility
other Windows-native approach
原則：不要做 Web UI。
A3. Installer technology
尚未定案：
Inno Setup
WiX
其他 Windows installer
要求：
Windows uninstall information
Client Task Scheduler installation/removal
Server Firewall rule installation/removal
admin elevation
Server Storage Root selection
Client Server IPv4 input
A4. Server configuration transport timing
目前方向：每次成功 Upload 的 HTTP 200 response 順便回傳最新 Client 設定。
尚未定案的細節：
是否在 Client 啟動時做一次 config-only request
設定變更後是否等下一張正常 upload 才生效
Cache recovery upload 是否同樣更新 Last Known Good Config
已確定原則：
> Server 沒回應時，Client 使用最後一次成功設定，不可停止工作。
A5. Exact local cache location
目前建議：
```text
C:\ProgramData\ScreenshotClient\Cache\
```
但尚未視為不可修改的最終規格。
目前不處理特殊 ACL。
A6. Image duplicate edge case
正常檔名使用：
```text
YYYYMMDD_HHMMSS_CC.jpg
```
`CC` 是厘秒，不是序號。
若極端情況完全相同 timestamp，Server 必須防止覆蓋或錯誤判斷，但正常檔名格式不加入序號。
A7. Logging level / location
尚未完全定案：
client log file path
server log file path
log rotation policy
default verbosity
原則：至少要能診斷 capture、upload、timeout、cache、recovery、server errors。
A8. Further security
MVP 明確不做 Client registration/token/password。
未來若部署到公司環境，可重新討論：
client credential
TLS/HTTPS
certificate validation
server-side access restrictions
audit logging
cache ACL
multi-client management
這些不應在 MVP 自行加入。
---
Part B — Grok First Prompt
使用方式
Grok 已連結 GitHub repository 後，第一輪只做 Repository Analysis。
禁止修改、禁止 commit、禁止建立 PR。
Prompt
```text
你現在是這個專案的 Senior Software Engineer。

重要：目前只做 Repository Analysis，不修改任何程式，不建立 commit，不建立 PR，不改 branch。

Repository 是從 `ciscoAnass/torcap` fork 出來、準備改造成 Windows Screenshot Monitor 的專案。

請先完整閱讀目前 repository 的所有主要檔案，特別是：

- app.py
- tor_server.py
- config.json
- server_config.json
- install.bat
- requirements.txt
- README.md

Repository 根目錄的規格文件：

- `00_PROJECT_OVERVIEW.md`
- `01_MVP_SPEC.md`
- `02_TORCAP_FILE_MAP.md`
- `03_AI_WORKFLOW.md`
- `04_PROJECT_HANDOFF.md`

請以 `01_MVP_SPEC.md` 為主要規格來源。

## 本次任務

### A. Current Architecture

說明目前 TorCap Client / Server 的實際架構，以及每個主要檔案的責任。

### B. Requirement Gap Analysis

逐條對照 `01_MVP_SPEC.md`，列出目前程式：

- 已符合
- 部分符合
- 不符合
- 完全沒有

### C. File-by-File Plan

對以下檔案逐一建議：

- keep
- modify
- major rewrite
- replace/delete

並說明原因。

### D. Architecture Proposal

提出你實際建議的新版 Client / Server 架構。

特別檢查：

1. Windows login startup
2. lock / unlock
3. sleep / wake
4. primary monitor
5. 25% x 25% resize
6. 8-bit grayscale
7. JPEG quality 20–100, default 40
8. screenshot interval default 20 sec
9. HTTP POST `/api/upload`
10. server TCP 55550
11. upload timeout 5 sec
12. HTTP 200 only after successful file write
13. success -> client does not retain image
14. failed upload -> local cache
15. 5 minute cache recovery scan
16. unlock / wake immediate recovery
17. complete cache upload, oldest first
18. duplicate upload protection
19. hostname + Windows username
20. server storage root configurable
21. client cache retention default 3 days
22. server retention default 14 days
23. last known good client configuration
24. server unavailable -> keep last known config and continue
25. Windows firewall rule for TCP 55550
26. Windows uninstall support

### E. Implementation order

請提出最小風險的 Phase 1 -> Phase N 實作順序。

不要一次重寫所有東西。

### F. Technical risks

指出你認為最可能出問題的 Windows / Python 技術細節，例如：

- desktop screenshot session
- lock state handling
- sleep/resume
- image conversion
- request timeout
- file I/O
- concurrent recovery upload
- duplicate uploads
- Task Scheduler
- Firewall rule
- installer/uninstaller

## Important constraints

- 不新增 SPEC 沒有要求的功能。
- 不要重新加入 Tor、SOCKS、`.onion`、Web Gallery、Web Login、ZIP 等舊 TorCap 功能。
- 不要做 Client registration/token system。
- 不要做 SQLite。
- 不要因為「可能未來需要」就把 MVP 做成企業級平台。
- 不要修改 repository。
- 不要 commit。
- 不要 PR。

最後請只回傳分析結果，格式：

1. Current Architecture
2. Requirement Gap Analysis
3. File-by-File Plan
4. Proposed Architecture
5. Implementation Phases
6. Technical Risks
7. Questions that must be decided before coding
```
---
Part C — ChatGPT New Project Start
C1. 建立 ChatGPT Project
建議名稱：
```text
Windows Screenshot Monitor
```
C2. Project knowledge
由於免費方案檔案數有限，目前只需要加入以下 5 份文件：
`00_PROJECT_OVERVIEW.md`
`01_MVP_SPEC.md`
`02_TORCAP_FILE_MAP.md`
`03_AI_WORKFLOW.md`
`04_PROJECT_HANDOFF.md`
其中 `04_PROJECT_HANDOFF.md` 已包含：
Open Technical Decisions
Grok First Prompt
ChatGPT New Project Start
C3. 新對話第一則訊息
```text
這是 Windows Screenshot Monitor 專案的新對話。

請先讀取 Project knowledge 中的所有專案文件，特別是：
- 00_PROJECT_OVERVIEW.md
- 01_MVP_SPEC.md
- 02_TORCAP_FILE_MAP.md
- 03_AI_WORKFLOW.md
- 04_PROJECT_HANDOFF.md

你在本專案的角色是：

ChatGPT = 需求、架構、規格、衝突裁決
Grok = 讀 repo、coding、branch、commit、PR
Gemini = 只 review，不與 Grok 同時修改同一個檔案

目前不要直接寫程式。
請先確認你已理解整個 MVP、AI 分工與 Git workflow。

接下來 Grok 會先對 GitHub repository 做只讀分析；我會把 Grok 的分析結果帶回這個對話，由你檢查是否符合 SPEC，再決定下一步。
```
C4. 後續節奏
```text
Grok 只讀分析
    ↓
把 Grok 分析貼回 ChatGPT
    ↓
ChatGPT 審查
    ↓
決定 Phase 1
    ↓
Grok coding
    ↓
Commit / PR
    ↓
Gemini review
    ↓
Review 結果帶回 ChatGPT
    ↓
ChatGPT 裁決
    ↓
Grok 修正
    ↓
下一 Phase
```
C5. 新對話一開始不要做
不要直接要求 ChatGPT 寫完整專案
不要直接讓 Grok 一次修改全部檔案
不要讓 Gemini 與 Grok 同時 edit 同一 branch
不要讓任何 AI 自行加入未定案功能
---
Part D — Project File Order
建議 ChatGPT Project knowledge 的閱讀優先順序：
```text
01_MVP_SPEC.md
    ↓
00_PROJECT_OVERVIEW.md
    ↓
02_TORCAP_FILE_MAP.md
    ↓
03_AI_WORKFLOW.md
    ↓
04_PROJECT_HANDOFF.md
```
理由：
`01` 是功能規格的最高優先依據。
`00` 說明專案定位與 AI 分工。
`02` 說明 TorCap 到新專案的檔案差異。
`03` 定義 Grok / Gemini / ChatGPT 的工作流程。
`04` 放尚未定案事項與啟動指令，不應反過來覆蓋已定案 SPEC。
衝突裁決規則
```text
01_MVP_SPEC.md
    >
技術實際狀況
    >
Grok 建議
    >
Gemini 建議
    >
舊 TorCap 行為
```
若 `01_MVP_SPEC.md` 沒有定義，而 Grok 與 Gemini 有不同意見，交由 ChatGPT 裁決。
