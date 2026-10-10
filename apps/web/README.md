# Web（Next.js）

教育局通告助手前端（`zh-HK` / `en`）。產品說明、本機啟動與 Coolify 部署見倉庫根目錄 [`README.md`](../../README.md)。

```bash
npm install
npm run dev   # http://localhost:4000
```

`npm run dev` 時，Next 把 `/api` 轉送到 `API_INTERNAL_URL`（未設則 `http://127.0.0.1:8008`）。請先啟動 API（或 `docker compose up`）。

正式部署走根目錄 Docker Compose + Coolify（DigitalOcean），**不是** Vercel。此套件不包含 Capacitor／原生 app。
