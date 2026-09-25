import httpx

r = httpx.post(
    "http://localhost:8008/api/auth/login",
    json={"username": "admin", "password": "000000"},
)
print(r.status_code, r.text[:300])
