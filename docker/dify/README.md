# Optional Dify profile (default off)

# Usage:
#   1. Place official Dify docker compose under this folder (or symlink).
#   2. docker compose --profile dify up -d
#   3. Set in root .env:
#        DIFY_ENABLED=true
#        DIFY_API_URL=http://dify-api:5001
#        DIFY_DATASET_API_KEY=...
#        DIFY_APP_API_KEY=...
#        DIFY_DATASET_ID=...
#
# The app already ships a no-op DifySync; when enabled it uploads documents
# to the dataset and can retrieve into chat knowledge_source modes:
# local | local_and_dify | dify

# Placeholder service so `profile: dify` is documented without bundling Dify.
# Replace with official Dify services when you need Knowledge.
services: {}
