# EDB Circulars Assistant

教育局通告／文件自動收集 + RAG 問答（Web / Android / iOS）。

## 功能

- 自動爬取公開通告與相關網站附件（`config/sources.yaml`）
- 檔案預設存本地 volume（可選 MinIO profile）；metadata + 向量存 Postgres（pgvector）
- Chat：Jina embeddings + OpenRouter LLM，回覆附引用
- 登入：`admin` / `000000`（請於生產環境更改）；Google OAuth API seam 已預留
- i18n：`zh-HK` / `en`，日期 `yyyy-mm-dd`
- 可選 Dify Knowledge（預設關閉）

## 快速開始

```bash
cp .env.example .env
# 填入 OPENROUTER_API_KEY、JINA_API_KEY（可先留空以 demo 模式啟動）

docker compose up --build -d
# Web 若映像未建好，可本機：cd apps/web && npm run dev
```

- Web: http://localhost:4000
- API: http://localhost:8008/docs
- Postgres host port: `5433`（避免與其他本機 Postgres 衝突）

登入後到「收集狀態」按「立即爬取」。

### 可選 profile

```bash
# MinIO 物件儲存（需可拉取 minio/minio）
docker compose --profile minio up -d
# 並設 STORAGE_BACKEND=minio

# Dify Knowledge（見 docker/dify/README.md）
docker compose --profile dify up -d
# 並設 DIFY_ENABLED=true 及 Dataset／API keys
```

## 本機開發（API）

```bash
cd apps/api
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
docker compose up -d db redis
# DATABASE_URL 指到 localhost:5433
uvicorn app.main:app --reload --port 8008
```

## 本機開發（Web）

```bash
cd apps/web
npm install
npm run dev   # http://localhost:4000
```

## Capacitor（Android / iOS）

Web 為主；行動版用 Capacitor 包同一 UI（開發時可指向已啟動的 Web）。

```bash
cd apps/web
# capacitor.config.json 的 server.url 預設 http://localhost:4000
npx cap add android
npx cap add ios
npx cap sync
npm run cap:android   # 或 cap:ios（需 macOS）
```

- Android：Android Studio 開啟 `android/`
- iOS：需 macOS + Xcode 開啟 `ios/`
- 實機請將 `NEXT_PUBLIC_API_URL` 與 Capacitor `server.url` 設為可連線的伺服器／區網位址（勿用 localhost）

## 環境變數重點

| 變數 | 說明 |
|------|------|
| `OPENROUTER_API_KEY` | LLM |
| `JINA_API_KEY` | Embeddings |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 種子管理員 |
| `JWT_SECRET` | 務必更改 |
| `STORAGE_BACKEND` | `local`（預設）或 `minio` |
| `DIFY_ENABLED` | 預設 `false` |
| `GOOGLE_CLIENT_ID` | 預留；未設則 `/api/auth/google` 回 501 |
| `LLM_PROVIDER` | `openrouter`（預設）或 `ollama` |

## 資料來源

見 [`config/sources.yaml`](config/sources.yaml)。P0：教育局通告系統、edb.gov.hk 附件（每日）；P1：姊妹學校、LWLSSG（每週）；P2：edcity（預設關閉）。

## 架構摘要

`Collector` → 本地檔／MinIO + Postgres → Jina embed → pgvector → `ChatService`（OpenRouter）  
可選：`DifySync` / `DifyKnowledgeBackend`。

## Coolify（DigitalOcean）部署

本機 `docker-compose.yml` 會把 API 綁到主機 `8008`。若仍出現 host port 衝突，用 Coolify override（見下）避免 publish 主機埠。

舊錯誤範例（若曾用 `8000`）：`Bind for 0.0.0.0:8000 failed: port is already allocated`

### 1. 在 droplet 上查誰佔用 8008（可選）

SSH 進 DigitalOcean droplet：

```bash
sudo ss -tlnp | grep ':8008'
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Ports}}' | grep 8008
```

若是本 stack 殘留容器，可先停掉；更穩妥的做法是改用下方 Coolify override，**不再** publish 主機 `8008`。

### 2. Compose 檔案

在 Coolify Docker Compose resource 設定 **兩個** compose 檔（順序重要）：

1. `docker-compose.yml`
2. `docker-compose.coolify.yml`

Override 會移除 `api` / `web` / `db` / `redis` 的 host port bind，改為僅 `expose`（由 Coolify Traefik 反代）。本機開發繼續只用 `docker compose up` 即可。

### 3. Coolify UI

- **Domains**：例如 `web` → 公開網域（內部 port `4000`）；`api` → `api.` 子網域（內部 port `8008`）
- **不要**再為 `8008` 設固定 Ports Mappings
- **Environment**：設 `NEXT_PUBLIC_API_URL=https://api.你的網域`（勿用 `http://127.0.0.1:8008`）
- 同步設好 `JWT_SECRET`、`ADMIN_PASSWORD`、`OPENROUTER_API_KEY`、`JINA_API_KEY` 等

部署後確認 log 無 port bind 錯誤；以 HTTPS 網域開啟 Web / API docs。

## 注意

- 只收集公開內容；遵守 rate limit
- 預設密碼僅供開發
- 「全部」為盡力而為；站點改版需更新 collector
