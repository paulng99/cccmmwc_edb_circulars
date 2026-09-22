import httpx

r = httpx.post(
    "http://localhost:8000/api/auth/login",
    json={"username": "admin", "password": "000000"},
)
print(r.status_code, r.text[:300])
