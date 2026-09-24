# Settings: edit sources.yaml + AI suggestions — Design

Date: 2026-09-24  
Status: Approved for planning  
Locale: en + zh-HK

## Goal

On the settings page, operators can list, add, edit, and remove crawl sources. Changes persist to `config/sources.yaml`. They can also ask AI to suggest sources from a topic or a pasted URL. Suggestions are searched with Jina first, shown for confirmation, and written only when the operator saves.

New and AI-suggested sources default to `enabled: false`. Saving does not start a crawl.

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| UI | Form list on the settings page (not a raw YAML editor) |
| AI input | Topic or URL |
| Discovery | Jina search (`https://s.jina.ai/`), then the existing LLM turns results into source drafts |
| Persist | Operator confirms, then Save writes `sources.yaml` |
| New sources | `enabled: false` until the operator turns them on |
| Collectors | Only `circular_aspnet` and `site_attachments` |
| Auth | Any authenticated user, same as settings |

## Non-goals

- New collector types
- Starting a crawl from this screen
- Deleting database `sources` rows or documents when a YAML entry is removed
- Preserving hand-written YAML comments (the file is rewritten; a short header is kept)
- Editing the YAML file outside this schema

---

## File format

Path: `SOURCES_CONFIG_PATH` (default `/config/sources.yaml`, repo file `config/sources.yaml`).

Header rewritten on every save:

```yaml
# Source registry. Edited from Settings. Collectors read this at crawl time.
sources:
  - id: example
    ...
```

Docker Compose: the **api** service mount changes from `./config:/config:ro` to `./config:/config`. Worker and beat stay read-only; they see host-file updates.

Writes are atomic: write a temp file in the same directory, then replace `sources.yaml`.

If the file on disk is not valid YAML or fails schema checks, `GET` returns 422 and does not modify the file. `PUT` of a valid list is still allowed so the operator can repair it.

---

## Source schema

Common fields:

| Field | Rule |
|-------|------|
| `id` | `^[a-z][a-z0-9_]{1,62}$`, unique in the file |
| `name.en` | non-empty string, max 200 |
| `name.zh-HK` | non-empty string, max 200 |
| `enabled` | boolean. Create and AI drafts use `false` |
| `priority` | integer 0–9 |
| `type` | `circular_aspnet` or `site_attachments` |
| `base_url` | `http` or `https` URL |
| `rate_limit_seconds` | number ≥ 0.5, default 1.5 |
| `schedule` | 5-field cron (`^\S+(\s+\S+){4}$`) |

`site_attachments` also requires:

| Field | Rule |
|-------|------|
| `allow_hosts` | non-empty list of hostnames |
| `file_extensions` | non-empty subset of `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx` |
| `seed_urls` | optional list of `http(s)` URLs; default is `[base_url]` at crawl time (omit when empty) |
| `path_prefixes` | optional list of path strings starting with `/` |
| `max_pages` | integer 1–5000, default 500 |

`circular_aspnet` also requires:

| Field | Rule |
|-------|------|
| `langs` | non-empty subset of `1` (en) and `2` (zh-HK) |
| `year_from`, `year_to` | integers 1990–2100, `year_from` ≤ `year_to` |

Unknown keys are rejected. At most 40 sources.

---

## API

Authenticated, same dependency as settings.

### `GET /api/sources/config`

Returns `{ "sources": [ ... ] }` using the schema above. 422 if the file cannot be loaded.

### `PUT /api/sources/config`

Body: `{ "sources": [ ... ] }`. Validate the full list. On success, atomically rewrite the YAML, then call existing `sync_sources_table` (upsert only). Do not enqueue a crawl.

Sources removed from YAML stay in the database and are not crawled, because crawl reads the YAML. This screen does not delete those rows.

### `POST /api/sources/suggest`

Body: `{ "mode": "topic" | "url", "query": "..." }`. `query` length 1–500.

Does not write the file.

1. Require `jina_api_key` from runtime settings. If missing, 400 `jina_not_configured`.
2. Search with `GET https://s.jina.ai/{query}` and `Authorization: Bearer <jina_api_key>`, `Accept: application/json`, timeout 30s.
   - `topic`: append ` site:edb.gov.hk OR site:edcity.hk` to the query.
   - `url`: query is the pasted URL; reject it unless it is `http` or `https`.
3. Send the search text plus the closed schema to the existing LLM client. The model returns a JSON array only (max 5 drafts).
4. Validate each draft with the same schema. Drop invalid drafts. Drop drafts whose `id` or normalized `base_url` already exists in the file on disk. The UI also hides drafts that match the current on-screen list, including unsaved rows.
5. Force `enabled: false` on every draft.

Response:

```json
{
  "suggestions": [],
  "dropped": 0
}
```

`dropped` is the count of drafts removed in step 4. Jina or LLM failure returns 502 and does not change the file. HTTP 200 with an empty `suggestions` array is success.

---

## Settings UI

New section **知識來源 / Knowledge sources** (en + zh-HK):

- List: zh-HK name, `id`, type, enabled toggle, edit, delete
- Add uses the same form. Type switches which extra fields are shown
- AI panel: mode topic or URL, query, button to suggest
- Suggestions render as unchecked drafts. **加入所選 / Add selected** appends them to the on-screen list with `enabled: false`
- **儲存 / Save** calls `PUT`. Nothing is written before Save
- Show API errors inline (invalid fields, missing Jina key, search failure)
- Saving does not navigate to crawl status and does not start a crawl

---

## Testing

Unit tests, no live Jina or LLM:

- Accept a valid `site_attachments` source and reject a bad `id`, unknown type, and empty `allow_hosts`
- Save then load returns the same sources (header comment present)
- Suggest keeps a valid draft, drops an invalid URL, and skips a `base_url` already in the file
- Suggest does not call the YAML writer

---

## Error handling

| Case | Result |
|------|--------|
| Invalid on-disk YAML | `GET` 422, file unchanged |
| `PUT` validation error | 422, file unchanged |
| Disk replace fails | 500, previous file remains if replace did not happen |
| No Jina key | suggest 400 |
| Jina or LLM error | suggest 502, file unchanged |
