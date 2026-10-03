AI Development Workflow
1. Roles
```text
                 ChatGPT
      PM / Architect / Specification
                 │
                 ▼
              SPEC.md
                 │
        ┌────────┴────────┐
        ▼                 ▼
      Grok              Gemini
   Engineer            Reviewer
        │                 │
        ▼                 │
     GitHub               │
   branch/commit          │
        │                 │
        └────── PR ───────┘
                  │
                  ▼
               Review
                  │
                  ▼
              ChatGPT
            final decision
```
2. Rules
ChatGPT
不隨意增加需求
不直接決定程式細節而忽略 SPEC
解決 Grok / Gemini 意見衝突
維護文件
Grok
先讀 repo
第一輪只分析，不修改
獲准後才 coding
使用 branch
小步驟 commit
每個 Phase 可測試
PR 說明修改內容與測試結果
Gemini
只 review
不與 Grok 同時修改同一檔案
優先 review bug、Windows 相容性、race condition、I/O、timeout、resource leak
對照 `01_MVP_SPEC.md`
3. Implementation phases
Phase 0 — Repository analysis
Grok：
讀完整 repository
不修改
提供 architecture + gap analysis
ChatGPT：
檢查 Grok 分析
決定實作路線
Phase 1 — Capture pipeline
目標：
login 啟動
primary monitor
screenshot
resize 25% x 25%
8-bit grayscale
JPEG encode
filename
不做 network。
Phase 2 — Upload
目標：
HTTP POST `/api/upload`
Server port 55550
HTTP 200 ACK
5 sec timeout
server write confirmation
success 不保存 local image
Phase 3 — Cache and Recovery
目標：
failed upload -> Cache
continue capture
5 minute scan
Unlock/Wake immediate recovery
all cache upload
oldest first
duplicate protection
success delete cache
client retention 3 days default
Phase 4 — Windows state handling
目標：
lock stop
unlock resume
sleep stop
wake resume
logoff stop
Phase 5 — Configuration
目標：
Server settings：
storage root
screenshot interval
JPEG quality
client cache days
server retention days
Client：
server IPv4
port 55550
last known good config
Server unavailable 時仍使用 last-known-good config。
Phase 6 — Retention
目標：
server 14 day default retention
automatic cleanup
client 3 day cache cleanup
Phase 7 — Installer / deployment
目標：
Client：
install
Task Scheduler
uninstall
no tray icon
Server：
install
storage root selection
firewall TCP 55550
uninstall
4. Review rule
Gemini 不需要 review 尚未完成的所有程式。
每次只 review 一個：
Phase
commit
PR
Review 結果分三類：
```text
PASS
PASS WITH FIXES
BLOCK
```
Gemini 不負責最終裁決。
5. Conflict resolution
遇到：
```text
Grok says A
Gemini says B
```
流程：
回到 `01_MVP_SPEC.md`
若 SPEC 已定義，照 SPEC
若 SPEC 未定義，交由 ChatGPT 決定
必要時更新 SPEC，再修改程式
6. Golden rule for coding
不要一次重寫所有東西。
每一 Phase 都要求：
```text
small diff
clear commit
test
review
then next phase
```
7. Test evidence
每個 Phase 完成後，Grok 應提供：
修改的檔案
主要改動
執行方式
測試結果
已知限制
下一步建議
不要只說「完成」。
