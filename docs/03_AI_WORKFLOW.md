# AI Development Workflow

更新：2026-10-06。Phase 0–7 已走完。下面的階段目標是開工計畫；實際結果以 `docs/05_PHASE_HISTORY.md` 與 `docs/01_MVP_SPEC.md` 為準。

已經改變的計畫：

- Phase 1 不再縮圖。現在是原始解析度、8-bit 灰階、JPEG。
- Phase 6 不是背景自動刪除。現在是每日第一次啟動時人工確認。
- Phase 7 使用 Inno Setup，不是改寫 `install.bat`。

## 1. Roles

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

## 2. Rules

ChatGPT 不隨意增加需求，解決 Grok / Gemini 衝突，維護文件。

Grok 先讀 repo，獲准後才改程式，使用 branch，小步驟 commit，每個 Phase 要能測試。

Gemini 只 review，不與 Grok 同時改同一檔案。優先看 bug、Windows 相容性、race condition、I/O、timeout、resource leak，並對照 `docs/01_MVP_SPEC.md`。

## 3. Implementation phases

以下是當初順序。狀態來自實機紀錄。

| Phase | 當初目標 | 實際 |
| --- | --- | --- |
| 0 | 只讀分析，不改程式 | 完成 |
| 1 | 截圖、當初含 25% 縮圖、灰階 JPEG | 通過；後改為原始解析度 |
| 2 | HTTP POST、55550、寫入後才 HTTP 200、5 秒逾時 | 通過 |
| 3 | 失敗進 Cache、5 分鐘補傳、重複保護 | 通過；300 秒實地補傳已確認，由舊到新，成功後刪除本機 Cache |
| 4 | 鎖定、睡眠、解鎖、喚醒 | 通過 |
| 5 | Server 設定與 Last Known Good | 通過 |
| 6 | 當初寫自動清理 | 通過；改為每日人工確認 |
| 7 | 安裝、工作排程、防火牆、解除安裝 | 通過 Windows 部署驗證 |

## 4. Review rule

Gemini 每次只 review 一個 Phase、commit 或 PR。結果分成 `PASS`、`PASS WITH FIXES`、`BLOCK`。Gemini 不做最終裁決。

## 5. Conflict resolution

先回 `docs/01_MVP_SPEC.md`。規格已定義就照規格。沒定義就交給 ChatGPT，必要時先改規格再改程式。

## 6. Coding rule

不要一次重寫所有東西。每個 Phase 要小 diff、清楚 commit、測試、review，再進下一 Phase。

完成時要交代修改檔案、主要改動、執行方式、測試結果、已知限制。不要只說完成。
