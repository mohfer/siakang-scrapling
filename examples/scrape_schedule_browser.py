"""CLI: class schedule via a real Camoufox browser (fallback).

Only needed if the plain-HTTP approach ever gets blocked. See
examples/scrape_schedule.py for the fast default path. Credentials come
from .env.
"""

import argparse
import json
import os
import re
import time

from dotenv import load_dotenv
from scrapling.fetchers import StealthyFetcher

from siakang import api_response

BASE = "https://siakang.untirta.ac.id"

TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}")


def _parse_card(card) -> dict:
    texts = [t.strip() for t in (card.inner_text() or "").split("\n") if t.strip()]
    link = card.query_selector('a[href*="/detail/"]')
    code = next(
        (x for x in texts[1:]
         if x and x[0].isupper() and any(ch.isdigit() for ch in x)
         and "SKS" not in x and "WIB" not in x and "Ruang" not in x),
        "",
    )
    sks = next((x.split()[0] for x in texts if x.endswith("SKS")), "")
    lecturer = next(
        (texts[i + 1] for i, x in enumerate(texts)
         if x.upper() == "DOSEN PENGAMPU" and i + 1 < len(texts)),
        "",
    )
    day = time_ = ""
    for x in texts:
        m = TIME_RE.search(x)
        if m and x.split():
            day = x.split()[0]  # keep the day name as Siakang provides it
            time_ = m.group()
    return {
        "name": texts[0],
        "code": code,
        "credits": int(sks) if sks.isdigit() else None,
        "lecturers": lecturer,
        "day": day,
        "time": time_,
        "href": link.get_attribute("href") if link else "",
    }


@api_response
def fetch_schedule(email: str, password: str, semester: str | None):
    courses: list[dict] = []

    def action(page):
        page.goto(f"{BASE}/auth/login", wait_until="domcontentloaded")
        page.wait_for_selector("#email", timeout=30000)
        page.fill("#email", email)
        page.fill("#password", password)
        with page.expect_navigation():
            page.click("button[type=submit]")

        # select the semester defined by SEMESTER in .env (None = active)
        if semester:
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
                semester,
            )
            if not href:
                raise SystemExit(f"Semester {semester} not found on list-semester")
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

        courses.extend(_parse_card(card) for card in page.query_selector_all("div.card")
                       if card.query_selector("h5") and card.query_selector('a[href*="/detail/"]'))

    StealthyFetcher.fetch(
        f"{BASE}/auth/login",
        headless=True,
        page_action=action,
        timeout=600000,
    )
    return courses


def main():
    parser = argparse.ArgumentParser(description="Scrape Siakang class schedule (browser fallback)")
    parser.add_argument("--json", action="store_true", help="Output full JSON envelope instead of a compact table")
    args = parser.parse_args()

    load_dotenv()
    email, password = os.getenv("EMAIL"), os.getenv("PASSWORD")
    if not (email and password):
        raise SystemExit("EMAIL/PASSWORD not set in .env")

    start = time.perf_counter()
    response = fetch_schedule(email, password, os.getenv("SEMESTER"))

    if args.json:
        print(json.dumps(response.to_dict(), ensure_ascii=False, indent=1))
    elif not response.ok:
        print(f"Error {response.code}: {response.message}")
    else:
        # same print style as docs/guide/getting-started.md §3
        for r in response.data:
            print(f"{r['code']} {r['name']} — {r['day']} {r['time']}")
    print(f"\nElapsed: {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
