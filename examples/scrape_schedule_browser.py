"""Fallback: scrape the class schedule using a real browser (Camoufox).

Only needed if the plain-HTTP approach ever gets blocked. See examples/scrape_schedule.py
for the fast default path.
"""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from scrapling.fetchers import StealthyFetcher

BASE = "https://siakang.untirta.ac.id"

load_dotenv()
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
SEMESTER = os.getenv("SEMESTER")
OUT = Path("/tmp/opencode/schedule_data.json")

TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}")


def fetch_all():
    def action(page):
        page.goto(f"{BASE}/auth/login", wait_until="domcontentloaded")
        page.wait_for_selector("#email", timeout=30000)
        page.fill("#email", EMAIL)
        page.fill("#password", PASSWORD)
        with page.expect_navigation():
            page.click("button[type=submit]")

        # select the active semester defined by SEMESTER in .env
        if SEMESTER:
            page.goto(f"{BASE}/dashboard/list-semester", wait_until="domcontentloaded")
            href = page.evaluate(
                """(code) => {
                    for (const c of document.querySelectorAll('.card-body')) {
                        if (c.innerText.includes('Kode Semester #' + code)) {
                            const a = c.querySelector('a[href*="change-semester"]');
                            return a ? a.href : null;
                        }
                    }
                    return null;
                }""",
                SEMESTER,
            )
            if not href:
                raise SystemExit(f"Semester {SEMESTER} not found on list-semester")
            page.goto(href, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")  # wait for the redirect after switching

        # schedule list view
        page.goto(f"{BASE}/jadwal_perkuliahan", wait_until="domcontentloaded")
        page.wait_for_selector("button", timeout=30000)
        for btn in page.query_selector_all("button, a"):
            if (btn.inner_text() or "").strip().lower() == "list view":
                btn.click()
                break
        page.wait_for_selector("div.card h5", timeout=30000)

        # parse every card
        courses = []
        for card in page.query_selector_all("div.card"):
            h5 = card.query_selector("h5")
            if not h5:
                continue
            body = card.query_selector(".card-body") or card
            texts = [t.strip() for t in (body.inner_text() or "").split("\n") if t.strip()]
            link = card.query_selector('a[href*="/detail/"]')
            courses.append({
                "raw": texts,
                "href": link.get_attribute("href") if link else "",
            })

        # fetch the class letter from each detail page
        for c in courses:
            c["class"] = ""
            if not c["href"]:
                continue
            page.goto(c["href"], wait_until="domcontentloaded")
            page.wait_for_function(
                "[...document.querySelectorAll('h5')].some(h => h.textContent.trim() === 'Kelas')",
                timeout=30000,
            )
            c["class"] = page.evaluate("""() => {
                const h = [...document.querySelectorAll('h5')].find(h => h.textContent.trim() === 'Kelas');
                let n = h.nextSibling;
                while (n && !n.textContent.trim()) n = n.nextSibling;
                return n ? n.textContent.trim() : '';
            }""")

        OUT.write_text(json.dumps(courses, ensure_ascii=False, indent=1))

    return StealthyFetcher.fetch(
        f"{BASE}/auth/login",
        headless=True,
        page_action=action,
        timeout=600000,
    )


def clean(s):
    return " ".join(str(s).split())


def main():
    OUT.unlink(missing_ok=True)  # avoid reading stale data when fetching fails
    fetch_all()
    courses = json.loads(OUT.read_text())

    print("| Code | Course Content | Lecturer | Credits | Day | Time |")
    print("|---|---|---|---|---|---|")
    for c in courses:
        raw = c["raw"]
        title = raw[0]
        # lines after the title: course code, schedule code, mode, credits
        code = next((x for x in raw[1:] if x and x[0].isupper() and any(ch.isdigit() for ch in x) and "SKS" not in x and "WIB" not in x and "Ruang" not in x), "")
        sks = next((x.split()[0] for x in raw if x.endswith("SKS")), "")
        lecturer = ""
        day, time_ = "", ""
        for i, x in enumerate(raw):
            if x.upper() == "DOSEN PENGAMPU" and i + 1 < len(raw):
                lecturer = raw[i + 1]
            m = TIME_RE.search(x)
            if m and x.split():
                day = x.split()[0]  # keep the day name as Siakang provides it
                time_ = m.group()
        class_letter = c.get("class", "")
        name = f"{title} ({class_letter[:1]})" if class_letter else title
        print(f"| {code} | {name} | {clean(lecturer)} | {sks} | {day} | {time_} |")


if __name__ == "__main__":
    main()
