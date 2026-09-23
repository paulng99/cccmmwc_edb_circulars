import httpx
from bs4 import BeautifulSoup
from pathlib import Path

BASE = "https://applications.edb.gov.hk/circular/circular.aspx?langno=2"
H = {"User-Agent": "Mozilla/5.0"}

with httpx.Client(headers=H, timeout=90, follow_redirects=True) as c:
    r = c.get(BASE)
    soup = BeautifulSoup(r.text, "lxml")

    def hid(n: str) -> str:
        el = soup.find("input", {"name": n})
        return el.get("value", "") if el else ""

    data = {
        "__VIEWSTATE": hid("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": hid("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": hid("__EVENTVALIDATION"),
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "ctl00$currentSection": "2",
        "ctl00$MainContentPlaceHolder$txtKeyword": "",
        "ctl00$MainContentPlaceHolder$ddlSchoolType2": "",
        "ctl00$MainContentPlaceHolder$ddlCircularType": "",
        "ctl00$MainContentPlaceHolder$txtCircularNumber": "",
        "ctl00$MainContentPlaceHolder$txtPeriodFrom": "1/1/2026",
        "ctl00$MainContentPlaceHolder$txtPeriodTo": "31/3/2026",
        "ctl00$MainContentPlaceHolder$btnSearch2": "Search",
    }
    r2 = c.post(BASE, data=data)
    Path(r"c:\Users\pauln\AppData\Local\Temp\edb_results.html").write_text(r2.text, encoding="utf-8")
    soup2 = BeautifulSoup(r2.text, "lxml")
    rows = soup2.select("table tr")
    print("rows", len(rows))
    count = 0
    for tr in rows:
        pdfs = [a for a in tr.select("a[href]") if (a.get("href") or "").lower().endswith(".pdf")]
        if not pdfs:
            continue
        tds = tr.find_all("td")
        print("---")
        print("td_count", len(tds))
        for i, td in enumerate(tds[:10]):
            print(i, repr(td.get_text(" ", strip=True)[:150]))
        for a in pdfs:
            print("pdf", repr(a.get_text(" ", strip=True)), (a.get("href") or "")[:100])
        count += 1
        if count >= 4:
            break
