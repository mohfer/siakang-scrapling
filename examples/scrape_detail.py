"""CLI: detail page for one course offering. Credentials come from .env."""

import argparse
import json
import os
import time

from dotenv import load_dotenv

from siakang import SiakangClient, TABS, api_response


@api_response
def fetch_detail(email: str, password: str, schedule_id: str | None, tabs: list[str] | None,
                 kuliah_id: str | None):
    with SiakangClient(email, password, session_file=True) as client:
        if schedule_id is None:
            courses = client.get_schedule()
            if not courses:
                raise SystemExit("No courses in the active semester schedule")
            schedule_id = courses[0]["schedule_id"]
            print(f"Using first course: {courses[0]['code']} {courses[0]['name']}\n")
        return client.get_detail(schedule_id, tab_keys=tabs, kuliah_id=kuliah_id)


def main():
    parser = argparse.ArgumentParser(description="Scrape one course detail page from Siakang")
    parser.add_argument("--schedule-id", help="Offering UUID from get_schedule(); default = first course")
    parser.add_argument("--tabs", nargs="+", default=["peserta"], choices=TABS,
                        help="Tab keys to fetch; default = peserta only. Any of: " + ", ".join(TABS))
    parser.add_argument("--kuliah-id", help="Jurnal meeting id (from pertemuan) to select")
    parser.add_argument("--json", action="store_true", help="Output full JSON instead of a compact summary")
    args = parser.parse_args()

    load_dotenv()
    email, password = os.getenv("EMAIL"), os.getenv("PASSWORD")
    if not (email and password):
        raise SystemExit("EMAIL/PASSWORD not set in .env")

    start = time.perf_counter()
    response = fetch_detail(email, password, args.schedule_id, args.tabs, args.kuliah_id)

    if args.json:
        print(json.dumps(response.to_dict(), ensure_ascii=False, indent=1))
    elif not response.ok:
        print(f"Error {response.code}: {response.message}")
    else:
        # same shapes as docs/guide/api-reference.md §get_detail
        detail = response.data
        for key, value in detail["header"].items():
            print(f"{key}: {value}")
        for tab, entry in detail["tabs"].items():
            if "rows" in entry:
                print(f"\n{tab}: {len(entry['rows'])} rows" + (f" (error: {entry['error']})" if entry["error"] else ""))
            else:
                counts = ", ".join(f"{k}={len(v)}" for k, v in entry["sections"].items())
                print(f"\n{tab}: sections {counts}" + (f" (error: {entry['error']})" if entry["error"] else ""))
    print(f"\nElapsed: {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
