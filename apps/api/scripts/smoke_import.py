from app.core.security import hash_password, verify_password
from app.collectors.registry import load_sources_config
from app.main import app

h = hash_password("000000")
print("hash_ok", verify_password("000000", h))
print("sources", len(load_sources_config()))
print("routes", len(app.routes))
