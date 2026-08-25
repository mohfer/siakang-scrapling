"""CLI: study results (grades) from /hasil-studi. Credentials come from .env."""

import argparse
import json
import os
import time

from dotenv import load_dotenv

from siakang import SiakangClient, api_response


@api_response
def fetch_grades(email: str, password: str, semester: str | None):
    with SiakangClient(email, password) as client:
        return client.get_grades(semester=semester)


def main():
    parser = argparse.ArgumentParser(description="Scrape Siakang study results")
    parser.add_argument("--semester", default=os.getenv("SEMESTER"), help="Semester code, e.g. 20251")
    parser.add_argument("--json", action="store_true", help="Output full JSON instead of a compact table")
    args = parser.parse_args()

    load_dotenv()
    email, password = os.getenv("EMAIL"), os.getenv("PASSWORD")
    if not (email and password):
        raise SystemExit("EMAIL/PASSWORD not set in .env")

    start = time.perf_counter()
    response = fetch_grades(email, password, args.semester or None)

    if args.json:
        print(json.dumps(response.to_dict(), ensure_ascii=False, indent=1))
    elif not response.ok:
        print(f"Error {response.code}: {response.message}")
    else:
        result = response.data
        print(f"IP: {result['ip']} | IPK: {result['ipk']}")
        print("| Code | Course | Lecturer | Credits | Score | Letter |")
        print("|---|---|---|---|---|---|")
        for c in result["courses"]:
            lecturer = ", ".join(c["lecturers"])
            print(f"| {c['code']} | {c['name']} | {lecturer} | {c['credits']} | {c['score']} | {c['letter']} |")
    print(f"\nElapsed: {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
