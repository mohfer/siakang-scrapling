# API Reference

Everything in this library revolves around one class: **`SiakangClient`**.
You create it with your Siakang login credentials, use it inside a `with`
block, and call its methods to fetch data.

```python
from siakang import SiakangClient

with SiakangClient(email="xxx@student.untirta.ac.id", password="...") as client:
    schedule = client.get_schedule()
```

The `with` block handles logging in and out for you. Every method below must be
called on a client opened this way — otherwise you get the error
*"Client is not open"*.

## Constructor Options

```python
SiakangClient(email, password, cache=None, max_workers=4, session_file=None)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `cache` | object with `get(key)` / `set(key, value)` | `None` | Caches parallel-class lookups (`schedule_id` → class letter) across runs. Use [`FileCache`](#constructor-options) for development, Redis/DB-backed stores for production. |
| `max_workers` | `int` | `4` | Parallel fetches when resolving class letters. |
| `session_file` | `str \| Path \| bool \| None` | `None` | Persists login cookies so later runs skip the login round-trip. `True` uses a per-account file derived from the email hash (each account gets its own file); a path string uses that exact file. Expired sessions automatically fall back to a full login. |

```python
from siakang import FileCache

client = SiakangClient(email, password,
                       cache=FileCache(),       # reuse class-letter lookups
                       session_file=True)       # skip re-login between runs
```

::: warning session_file holds live credentials
The session file contains valid login cookies — treat it like a password.
Its location follows the current working directory unless you pass an explicit
path, and it should never be committed to version control.
:::

---

## Quick Overview

| Method | What it returns | Source page |
|---|---|---|
| [`list_semesters()`](#list-semesters) | All semesters you can switch to | `/dashboard/list-semester` |
| [`get_schedule()`](#get-schedule) | Your weekly class schedule | `/jadwal_perkuliahan` |
| [`get_grades()`](#get-grades) | Study results: scores, letters, IP & IPK | `/hasil-studi` |
| [`get_detail()`](#get-detail) | Everything about one course offering | `/jadwal_perkuliahan/detail/<id>` |

All of them return **plain Python dictionaries** — no custom objects — so you
can freely serialize them to JSON.

---

## list_semesters

Lists every semester available on your account, newest first. Useful to
discover which semester codes exist before calling other methods.

```python
semesters = client.list_semesters()
```

**Parameters:** none.

**Returns** a list of dicts:

```python
[{
    "code": "20261",                    # use this in get_schedule(semester=...)
    "name": "2026/2027 Gasal",
    "id": "019c0c58-a01f-...",          # internal UUID
    "active": True,                     # True = currently selected on your account
}, ...]
```

::: tip When would I use this?
When you don't know the semester code, or you want to show a semester picker
in your own app.
:::

## get_schedule

Fetches your **weekly class schedule** — the same cards you see under
*Perkuliahan → Jadwal Perkuliahan* in List View.

```python
rows = client.get_schedule()                      # active semester
rows = client.get_schedule(semester="20252")      # specific semester
```

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `semester` | `str \| None` | `None` | Semester code from `list_semesters()` (`"code"` field). `None` keeps whatever semester is currently selected in this session. |
| `detail` | `bool` | `False` | When `True`, every row also carries a `detail` object (see [get_detail](#get-detail)). Much slower — one extra page load per course. |

**Returns** a list of dicts, one per course:

```python
[{
    "name": "Mata Kuliah Satu",       # course name
    "code": "INF600001",              # course code (e.g. used as subject identifier)
    "schedule_code": "2600000001",    # schedule/offering code shown on the site
    "mode": "Offline",                # Offline / Online / Hybrid
    "credits": 2,                     # SKS
    "schedules": [                    # one entry per weekly session
         {"day": "Senin", "time": "07:30 - 09:10",
          "room": "Ruang Kuliah Contoh 101"},
    ],
    "lecturers": ["Dosen Contoh"],   # teaching team
    "class": "C24",                   # full class label; first letter is the parallel class
    "schedule_id": "019bde9b-...",    # offering UUID — key for caches & get_detail
}]
```

Raises `SiakangNotFoundError` if the given `semester` code doesn't exist.

## get_grades

Fetches your **study results** from *Rencana Studi → Hasil Studi*: per-course
scores plus the semester GPA (**IP**) and cumulative GPA (**IPK**).

```python
result = client.get_grades()                  # current session's semester
result = client.get_grades(semester="20251")  # specific semester
```

**Parameters:** same `semester` behaviour as [get_schedule](#get-schedule).

**Returns:**

```python
{
    "ip": 3.50,     # float | None — None until grades are published
    "ipk": 3.40,    # float | None
    "courses": [{
        "no": 1,
        "schedule_code": "2600000001",
        "name": "Mata Kuliah Satu",
        "code": "INF600001",
        "credits": 2,
        "lecturers": ["Dosen Satu, S.T., M.T."],
        "score": 85.0,     # Nilai — None until published
        "letter": "B+",    # Mutu — None until published
    }, ...]
}
```

::: warning Grades not published yet?
If a lecturer hasn't released the grades, `score`, `letter`, `ip` and `ipk`
come back as `None`. That is normal — check again later.
:::

## get_detail

Opens the **detail page of one course offering** and collects everything on it:
the header card (Kode Jadwal, Kelas, Dosen, Ruang dan Waktu, Pertemuan
Terlaksana) plus all four tabs — RPS & Bahan Ajar, Peserta (participants),
Jurnal Perkuliahan and Rekap Jurnal Perkuliahan.

```python
detail = client.get_detail("019bde9b-a01f-...")       # a schedule_id
```

Where do I get a `schedule_id`? From any row of
[`get_schedule()`](#get-schedule) — it's the `"schedule_id"` field.

**Returns:**

```python
{
    "url": "https://siakang.untirta.ac.id/jadwal_perkuliahan/detail/<id>",
    "header": {
        "Kode Jadwal": "2600000001",
        "Mata Kuliah": "Mata Kuliah Satu",
        "Kelas": "A24",
        "Dosen": "Dosen Dummy, S.T., M.T.I",
        "Ruang dan Waktu": "Ruang Kuliah Contoh 101, Senin 09:10 - 10:50",
        "Pertemuan Terlaksana": "0 Kali",
    },
    "tabs": {
        "rps_bahan_ajar":            { "tables": [...], "text": "...", "error": None },
        "peserta":                   { "tables": [...], "text": "...", "error": None },
        "jurnal_perkuliahan":        { "tables": [...], "text": "...", "error": None },
        "rekap_jurnal_perkuliahan":  { "tables": [...], "text": "...", "error": None },
    }
}
```

Each tab contains:

- `tables` — list of `{headers: [...], rows: [[cell, ...], ...]}`, extracted
  from every HTML table found in that tab.
- `text` — plain-text version of the whole tab (handy for search/preview).
- `error` — set only when the Siakang server itself failed to render the tab;
  the rest of the response stays usable.

::: tip detail=True shortcut
Instead of looping manually, call
`client.get_schedule(detail=True)` once — every schedule row then already
contains its own `detail` object.
:::

## Errors

Every failure raises a subclass of `SiakangError`:

| Exception | Meaning |
|---|---|
| `SiakangAuthError` | Wrong email/password, or the session expired mid-run |
| `SiakangNotFoundError` | The requested semester doesn't exist |
| `SiakangUpstreamError` | Siakang server misbehaved or changed; usually retry later |

See [Errors & Responses](./errors-and-responses) for turning these into clean
API responses automatically.
