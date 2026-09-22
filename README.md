# EDB Circulars Assistant

教育局通告／文件自動收集 + RAG 問答（Web / Android / iOS）。

## 功能

- 自動爬取公開通告與相關網站附件（`config/sources.yaml`）
- 檔案存 MinIO，metadata + 向量存 Postgres（pgvector）
- Chat：Jina embeddings + OpenRouter LLM，回覆附引用
- 登入：`admin` / `000000`（請於生產環境更改）
- i18n：`zh-HK` / `en`，日期 `yyyy-mm-dd`
- 可選 Dify Knowledge（預設關閉）

## 快速開始

```bash
cp .env.example .env
# 填入 OPENROUTER_API_KEY、JINA_API_KEY（可先留空以 demo 模式啟動）

docker compose up --build
```

- Web: http://localhost:4000
- API: http://localhost:8000/docs
- MinIO console: http://localhost:9001

登入後到「收集狀態」按「立即爬取」。

## 本機開發（API）

```bash
cd apps/api
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# 需要已啟動的 db/redis/minio（可用 docker compose up db redis minio -d）
uvicorn app.main:app --reload --port 8000
```

## 本機開發（Web）

```bash
cd apps/web
npm install
npm run dev
```

## Capacitor（Android / iOS）

Web 為主；行動版用 Capacitor 包同一 UI。

```bash
cd apps/web
# 建議先把 next.config 改為可靜態匯出，或指向已部署的 HTTPS API
npx cap add android
npx cap add ios
npx cap sync
```

- Android：Android Studio 開啟 `android/`
- iOS：需 macOS + Xcode 開啟 `ios/`
- 請將 `NEXT_PUBLIC_API_URL` 設為手機可連線的伺服器位址（勿用 localhost）

## 環境變數重點

| 變數 | 說明 |
|------|------|
| `OPENROUTER_API_KEY` | LLM |
| `JINA_API_KEY` | Embeddings |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 種子管理員 |
| `JWT_SECRET` | 務必更改 |
| `DIFY_ENABLED` | 預設 `false` |
| `LLM_PROVIDER` | `openrouter`（預設）或 `ollama` |

## 資料來源

見 [`config/sources.yaml`](config/sources.yaml)。P0：教育局通告系統、edb.gov.hk 附件；P1：姊妹學校網站等。

## 架構摘要

`Collector` → MinIO + Postgres → Jina embed → pgvector → `ChatService`（OpenRouter）  
可選：`DifySync` 同步 Knowledge。

## 注意

- 只收集公開內容；遵守 rate limit
- 預設密碼僅供開發
- 「全部」為盡力而為；站點改版需更新 collector
