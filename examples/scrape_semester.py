"""CLI: semester list from /dashboard/list-semester. Credentials come from .env."""

import os
import time

from dotenv import load_dotenv

from siakang import SiakangClient, api_response


@api_response
def fetch_semesters(email: str, password: str):
    with SiakangClient(email, password, session_file=True) as client:
        return client.list_semesters()


def main():
    load_dotenv()
    email, password = os.getenv("EMAIL"), os.getenv("PASSWORD")
    if not (email and password):
        raise SystemExit("EMAIL/PASSWORD not set in .env")

    start = time.perf_counter()
    response = fetch_semesters(email, password)

    if not response.ok:
        print(f"Error {response.code}: {response.message}")
    else:
        print("| Code | Semester | ID | Active |")
        print("|---|---|---|---|")
        for s in response.data:
            print(f"| {s['code']} | {s['name']} | {s['id']} | {'Yes' if s['active'] else ''} |")
    print(f"\nElapsed: {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
