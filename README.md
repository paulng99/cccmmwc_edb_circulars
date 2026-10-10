# 教育局通告助手（EDB Circulars）

學校職員用的教育局通告庫：**收集入庫 → 搜尋／問答 → 活動開始／截止月曆 → 通告詳情（PDF 原文 +「要學校做什麼」撮要）**。

正式站點：[https://ecircular.paulsir.com](https://ecircular.paulsir.com)（DigitalOcean + Coolify；網域經 Cloudflare）。

i18n：`zh-HK` / `en`；日期格式 `yyyy-mm-dd`。

---

## 功能

### 收集與文件庫

- 按 [`config/sources.yaml`](config/sources.yaml) 爬取公開通告／附件（設定頁可改來源）
- 檔案預設存本地 volume（可選 MinIO）；metadata + 向量存 Postgres（pgvector）
- 通告詳情：保留 **PDF／原文**；下方顯示學校行動撮要（見下）
- 通告發出／修訂日另由 `doc_dates` 本機規則處理（與活動開始／截止日無關）

### 問答（RAG）

- Jina embeddings + OpenRouter（或設定中的 Ollama）回答模型
- 回覆附引用；必要時可改為搜尋公開網頁並標明來源
- 可選 Dify Knowledge（預設關閉；見 [`docker/dify/README.md`](docker/dify/README.md)）

### 活動月曆（LLM 抽出開始／截止日）

- **開始日／截止日只經 LLM**（`get_llm_client()`，與問答同一回答模型路徑）
- 啟動時全庫 backfill + 新文件 ingest／index 皆走此路徑；標記 `activities_parsed=llm-1`
- LLM 失敗：**清空該通告活動日期**，**沒有**本機 regex 後備；不會為缺漏活動列發明「未有」
- 本機活動日期 collector（`collectors/activity_dates.py`）已刪除，勿再當現行功能
- 準確度 **未驗證**（未以真實通告庫核對）
- UI：
  - Backfill 進行中：顯示「日期更新中」（`dates_updating`）
  - 月曆無日期：顯示「暫未有開始日或截止日」（不是「尚未抽出」）
  - 議程標題兩行：事項名在上、通告標題在下（同字級；抽不到事項名時只顯示通告標題）

### 重新分析（學校行動撮要）

- 在文件列表 **多選** 通告 →「重新分析」
- **只把所選通告正文** 送到回答模型，寫入 `extra.school_action`：以「未核對」為前綴的一段「這份要學校做什麼」
- 失敗：保留該份舊撮要；PDF／原文不變，撮要仍在原文下方
- 來源可開 **自動 AI 分析**（入庫後自動跑撮要）；活動日期仍在 ingest 另走 LLM，不依賴此開關

### 兩次獨立的 LLM 呼叫

| 用途 | 送出內容 | 失敗行為 |
|------|----------|----------|
| 學校行動撮要（重新分析／自動分析） | 所選／該份通告正文 | **保留**舊 `school_action` |
| 活動開始／截止日 | 通告正文 | **清空**活動日期（無 regex 後備） |

二者是 **分開** 的 LLM 請求，不要當成一次合併呼叫。

### 設定

- 登入：`ADMIN_USERNAME` / `ADMIN_PASSWORD`（`.env.example` 預設 `admin` / `000000`，生產必須更改）
- 設定頁「用 AI 改寫系統提示詞」：**尚未開啟**（按鈕 disabled，標「尚未開啟」），待明確批准前勿當可用功能

---

## 本機執行

```bash
cp .env.example .env
# 填 OPENROUTER_API_KEY、JINA_API_KEY（可留空以 demo 模式啟動）

docker compose up --build -d
```

| 服務 | 位址 |
|------|------|
| Web | http://localhost:4000 |
| API docs | http://localhost:8008/docs |
| Postgres（主機埠） | `5433` |

登入後到「收集狀態」按「立即爬取」。

### 本機分開跑 API + Web

```bash
# 依賴
docker compose up -d db redis

# API
cd apps/api
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# DATABASE_URL 指到 localhost:5433
uvicorn app.main:app --reload --port 8008

# Web（另開終端）
cd apps/web
npm install
npm run dev   # http://localhost:4000
```

Web 以 `/api` 轉送 API：`API_INTERNAL_URL` 在 Compose 內為 `http://api:8008`；本機 `npm run dev` 未設時預設 `http://127.0.0.1:8008`。`NEXT_PUBLIC_API_URL` 通常留空。

### 可選 profile

```bash
docker compose --profile minio up -d   # 並設 STORAGE_BACKEND=minio
docker compose --profile dify up -d    # 並設 DIFY_ENABLED=true 等（見 docker/dify）
docker compose --profile tools up -d adminer
```

### 環境變數（摘要，不含密鑰）

| 變數 | 說明 |
|------|------|
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | 回答模型（問答、撮要、活動日期） |
| `JINA_API_KEY` | Embeddings／rerank |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 種子管理員 |
| `JWT_SECRET` | 務必更改 |
| `STORAGE_BACKEND` | `local`（預設）或 `minio` |
| `LLM_PROVIDER` | `openrouter`（預設）或 `ollama` |
| `DIFY_ENABLED` | 預設 `false` |
| `API_INTERNAL_URL` | Web 容器轉送 `/api` 的目標 |
| `NEXT_PUBLIC_API_URL` | 留空；僅在瀏覽器要直連另一公開 API 時於**建置**時設定 |
| `GOOGLE_CLIENT_ID` | 預留；未設則 Google 登入回 501 |

完整範例見 [`.env.example`](.env.example)。

---

## 部署（DigitalOcean + Coolify）

- **主機**：DigitalOcean droplet；**編排**：Coolify（Docker Compose）
- **網域**：Cloudflare → `ecircular.paulsir.com`（瀏覽器只連 Web；Web 轉送 `/api`）
- Coolify resource 使用兩個 compose 檔（順序重要）：
  1. `docker-compose.yml`
  2. `docker-compose.coolify.yml`（移除 host port bind，改 `expose`；config 用 named volume）
- **Domains**：`web` → 公開網域（內部 port `4000`）。**不要**把 `8008` 暴露到公網
- Environment：`API_INTERNAL_URL=http://api:8008`；`NEXT_PUBLIC_API_URL` 留空；設好 `JWT_SECRET`、`ADMIN_PASSWORD`、`OPENROUTER_API_KEY`、`JINA_API_KEY` 等
- 改 `NEXT_PUBLIC_*` 後須**重新建置** web image
- Coolify 通常以 **Git `main` webhook** 自動部署；**push 到 `main` 可能觸發重建**。本 README 不記載 Coolify 內部 UUID

本機開發繼續只用 `docker compose up` 即可。

---

## 資料與私隱

本應用處理的是**公開教育局通告／附件**與職員帳號，**不收集學生個人資料（PII）**。

會離開本機伺服器、送到外部模型／服務的內容包括：

| 情況 | 送出內容 |
|------|----------|
| 重新分析／自動學校行動撮要 | **所選或該份**通告**正文**（索引 chunks；必要時才從 PDF 抽字） |
| 活動開始／截止日（backfill／ingest／重新分析時的日期路徑） | 通告**正文** |
| 問答 | 使用者問題 + 檢索到的通告片段（及設定允許時的網頁摘要）；embeddings 經 Jina |
| 嵌入入庫 | 通告文本 chunks → Jina |

**不會**因「重新分析」而送出未選中的通告。PDF 檔案本身留在伺服器儲存；撮要失敗不覆蓋舊文。

---

## 現況與限制

- 活動日期與學校行動撮要的**準確度均未驗證**（未核對）
- 本機活動日期 regex **已廢止／刪除**；勿再依賴
- 設定頁 AI 改寫系統提示詞：**關閉**
- 只收集公開內容；遵守 rate limit；「全部」為盡力而為，站點改版需更新 collector
- 預設管理員密碼僅供開發
- **無** Capacitor／原生 mobile 套件；以 Web 為準

### 架構摘要

`Collector` → 本地檔／MinIO + Postgres → Jina embed → pgvector → `ChatService`（OpenRouter）  
活動日期／學校撮要：`get_llm_client()` 分開呼叫 · 可選 `DifySync`
