import httpx

base = "http://localhost:8008"
login = httpx.post(f"{base}/api/auth/login", json={"username": "admin", "password": "000000"})
print("login", login.status_code)
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
g = httpx.post(f"{base}/api/auth/google", json={"id_token": "x"})
print("google", g.status_code, g.json())
st = httpx.get(f"{base}/api/ingest/status", headers=headers)
print("status", st.status_code, st.json().get("documents"))
crawl = httpx.post(f"{base}/api/ingest/crawl?source_id=edb_circulars", headers=headers)
print("crawl", crawl.status_code, crawl.json())
