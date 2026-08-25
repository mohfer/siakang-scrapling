<div align="center">

# siakang-scrapling

*Fetch Siakang Untirta data over pure HTTP — schedules, grades and semesters*

[![Python](https://img.shields.io/badge/Python-3.11%2B-3c873a?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-58%20passed-3c873a?style=flat-square)](tests)
[![Docs](https://img.shields.io/badge/docs-VitePress-5da9ff?style=flat-square)](https://docs-siakang-scrapling.mohfer.my.id)

[Features](#features) • [Installation](#installation) • [Quickstart](#quickstart) • [API](#api-overview) • [CLI](#command-line)

</div>

A Python library that reads data from [Siakang Untirta](https://siakang.untirta.ac.id) —
the academic information system of Sultan Ageng Tirtayasa University — using plain HTTP
requests with browser impersonation. No headless browser, no JavaScript engine.

## Features

- 📅 **Class Schedule** — weekly sessions with day, time, room and teaching team
- 🎓 **Study Results** — per-course scores, letters, plus semester GPA (IP) and cumulative GPA (IPK)
- 🗓️ **Semester List** — every semester your account can switch to, with codes and UUIDs
- 🔍 **Course Details** — participants, RPS documents, journals and attendance recaps
- ⚡ **Fast & Lightweight** — Livewire calls replayed directly; a full schedule takes ~2 seconds
- 🧩 **Consistent Responses** — optional `{code, message, data}` envelope for app integration

## Installation

```bash
uv add git+https://github.com/mohfer/siakang-scrapling
```

Requires Python 3.11+. The main dependency is
[Scrapling](https://scrapling.readthedocs.io), which provides the browser-impersonated
HTTP client.

## Quickstart

```python
from siakang import SiakangClient

with SiakangClient(email="xxx@student.untirta.ac.id", password="...") as client:
    # weekly class schedule for the active semester
    for course in client.get_schedule():
        session = course["schedules"][0]
        print(f"{course['code']} {course['name']} ({course['class']}) "
              f"— {session['day']} {session['time']}")

    # study results for a specific semester
    result = client.get_grades(semester="20251")
    print("IP:", result["ip"], "| IPK:", result["ipk"])

    # everything about one course offering
    detail = client.get_detail(course["schedule_id"])
    print(detail["header"]["Dosen"])
```

> [!TIP]
> Every method returns plain dictionaries, so you can freely serialize results
> with `json.dumps()`. See the full field-by-field output in the
> [API reference](https://docs-siakang-scrapling.mohfer.my.id/guide/api-reference).

### Consistent API responses

Wrap any call with the `@api_response` decorator so consumers always receive a
`{code, message, data}` envelope instead of exceptions:

```python
from siakang import SiakangClient, api_response

@api_response
def fetch_schedule(email: str, password: str, semester: str | None):
    with SiakangClient(email, password) as client:
        return client.get_schedule(semester=semester)

response = fetch_schedule(email, password, "20252")
print(response.to_dict())   # {"code": 200, "message": "Success", "data": [...]}
```

| Code | Meaning |
|---|---|
| `200` | Success |
| `400` | Usage error |
| `401` | Wrong credentials or expired session |
| `404` | Semester not found |
| `500` | Unexpected internal error |
| `502` | Siakang server failure or page changed |

## API Overview

| Method | Description |
|---|---|
| `list_semesters()` | All semesters with codes, names, UUIDs and the active flag |
| `get_schedule(semester?, detail?)` | Weekly class schedule; one row per course |
| `get_grades(semester?)` | Study results with scores, letters, IP and IPK |
| `get_detail(schedule_id)` | Header card + RPS, participants, journals and recap tabs |

Full parameter tables and output shapes:
the [API Reference](https://docs-siakang-scrapling.mohfer.my.id/guide/api-reference).

## Command Line

Ready-made tools in [`examples/`](examples/) read credentials from `.env`
(see [`.env.example`](.env.example)):

```bash
cp .env.example .env                                # fill in EMAIL / PASSWORD / SEMESTER

uv run python examples/scrape_schedule.py           # schedule, one line per course (--json for full output)
uv run python examples/scrape_grades.py             # study results
uv run python examples/scrape_semester.py           # semester list
```

## Caching & Multi-user Notes

The parallel class only exists on each course's detail page. It belongs to the
*course offering*, not the student, so its cache key (`schedule_id`) can safely be
shared across users:

```python
from siakang import FileCache

client = SiakangClient(email, password, cache=FileCache())   # dev default
```

For production apps backed by Redis or a database, pass any object exposing
`get(key)` / `set(key, value)`. Each `SiakangClient` instance owns an isolated
HTTP session — create one per logged-in user and never share it across threads.

### Skip re-login between runs

Pass `session_file=True` and login cookies are saved to a per-account file, so the
next run restores the session instead of logging in again (expired sessions fall
back to a full login automatically):

```python
client = SiakangClient(email, password, session_file=True)
# cookies stored in .siakang_session_<email-hash>.json — one file per account,
# or pass an explicit path to choose your own location.
```

The session file contains live login cookies — treat it like a password.

## How It Works

Siakang is a Laravel + Livewire application. Instead of running a browser, this
library replays the same HTTP calls: it parses each component's serialized
`wire:snapshot`, sends property updates to `/livewire/update`, and reproduces
lazy-load commits (`__lazyLoad`) to render detail pages and tabs.

Curious about the details? Read
[How It Works](https://docs-siakang-scrapling.mohfer.my.id/guide/how-it-works).
