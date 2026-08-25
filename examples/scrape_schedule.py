"""CLI: class schedule table. Credentials & semester come from .env."""

import argparse
import json
import os
import time

from dotenv import load_dotenv

from siakang import FileCache, SiakangClient, api_response


@api_response
def fetch_schedule(email: str, password: str, semester: str | None, detail: bool):
    with SiakangClient(email, password, cache=FileCache(), session_file=True) as client:
        return client.get_schedule(semester=semester, detail=detail)


def main():
    parser = argparse.ArgumentParser(description="Scrape Siakang class schedule")
    parser.add_argument("--semester", default=os.getenv("SEMESTER"), help="Semester code, e.g. 20252")
    parser.add_argument("--detail", action="store_true", help="Include full detail pages for every course (slow)")
    parser.add_argument("--json", action="store_true", help="Output full JSON instead of a compact table")
    args = parser.parse_args()

    load_dotenv()
    email, password = os.getenv("EMAIL"), os.getenv("PASSWORD")
    if not (email and password):
        raise SystemExit("EMAIL/PASSWORD not set in .env")

    start = time.perf_counter()
    response = fetch_schedule(email, password, args.semester or None, args.detail)

    if args.json:
        print(json.dumps(response.to_dict(), ensure_ascii=False, indent=1))
    elif not response.ok:
        print(f"Error {response.code}: {response.message}")
    else:
        # same loop as docs/guide/getting-started.md §3
        for row in response.data:
            sesi = row["schedules"][0]
            print(f"{row['code']} {row['name']} — {sesi['day']} {sesi['time']}")
    print(f"\nElapsed: {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
