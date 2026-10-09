# School-action AI icon + activity re-extract — Design

**Date:** 2026-10-09  
**Status:** Approved

## Problem

「未核對」文字標記不直觀；用戶希望用 AI icon 表示 LLM 產出，並在確認後可再跑一次分析。同時應重新抽出該通告所有活動的開始／截止日期。

## Goals

- 詳情頁以 AI（sparkles）icon 取代「未核對」字樣顯示。
- 按 icon → 確認 → 以 LLM 重新分析 school action，並以 LLM 重抽 `activities`。
- 回應與 UI 同步更新行動段落與活動日期列表。
- i18n：`zh-HK` / `en`；日期 `yyyy-mm-dd`。

## Non-goals

- 用人機核對流程把「未核對」改成「已核對」狀態機。
- 改動月曆頁版面。
- 遷移／移除 DB 內既有「未核對\n」前綴（顯示層剝除即可）。

## Decisions

| Topic | Choice |
|-------|--------|
| Approach | 擴充現有 `POST /api/documents/reanalyze` |
| Activity extract | LLM JSON（失敗時 fallback 本地 regex） |
| LLM 失敗時 | 保留舊 school_action；activities 仍可經 LLM／regex 更新 |
| Storage | 繼續寫入「未核對」前綴（相容）；UI 剝除後顯示 |
| Icon | 現有 `sparkles` |
| Confirm | dialog + i18n 文案 |

## UI

- 詳情頁「這份要學校做什麼」標題旁：可點 AI icon（`aria-label`／title）。
- 正文不顯示「未核對」。
- 清單頁 `school_action` 摘要同樣剝除前綴。
- 進行中：icon loading／disabled；完成後更新本頁 `school_action` + `activities`。

## API

`ReanalyzeItemOut` 增加 `activities: list[DocumentActivityOut]`。  
`reanalyze_one`：載入正文後以 LLM 抽 activities（regex fallback）；另一次 LLM 更新 school_action。

## Tests

- API：成功時 activities 來自 LLM；school_action 失敗時仍可更新 activities；activities LLM 失敗則 regex fallback。
- Web helper：剝除「未核對」前綴。
