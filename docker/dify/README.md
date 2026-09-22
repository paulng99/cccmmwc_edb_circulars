# Optional Dify Knowledge profile

## Enable

1. Obtain / clone official Dify docker compose into this folder (or symlink).
2. Start:

```bash
docker compose --profile dify up -d
```

3. In root `.env`:

```
DIFY_ENABLED=true
DIFY_API_URL=http://dify-api:5001
DIFY_DATASET_API_KEY=...
DIFY_APP_API_KEY=...
DIFY_DATASET_ID=...
```

4. Restart `api` / `worker` so they pick up env.

## App behaviour

- `DifySync` uploads newly ingested files to the Dataset when enabled.
- Chat `knowledge_source`: `local` | `local_and_dify` | `dify`
- When `DIFY_ENABLED=false`, backends are no-ops — main RAG still works.

## RAM

Official Dify stack typically needs ≥8GB free RAM. Keep it off for small machines.
