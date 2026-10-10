# LLM activity dates — design

**Status:** Binding product decision implemented in PR (accuracy 未驗證).

**Approval:** Paul「同意送出日期」in the EDB room (distinct from prior「同意送出」for school-action reanalyze).

## Decision

Local regex calendar date extraction is voided for **display** and **backfill**. Start/deadline activities come from the answer-model LLM only (same client as reanalyze). On LLM failure for a document/item: omit dates — no regex fallback, no UI「未有」for failed LLM date fields.

## Behaviour

1. Full-library backfill on boot: clear stale local activities, set `activities_llm_backfill=in_progress`, extract via LLM, mark `activities_parsed=llm-1`, then `done`.
2. Ingest/index always uses the LLM path for activities (school-action auto-AI remains source-gated).
3. Multiple activities → separate calendar rows.
4. While backfill in progress: calendar + homepage show「日期更新中」via `dates_updating`.
5. Unchanged: document titles; school_action /「未核對」reanalyze; settings AI prompt rewrite (off).

## Accuracy

未驗證 until UR rechecks public EDBCM 140/2026 and 136/2026 after deploy.
