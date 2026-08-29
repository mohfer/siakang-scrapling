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
SiakangClient(email, password, session_file=None)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `session_file` | `str \| Path \| bool \| None` | `None` | Persists login cookies so later runs skip the login round-trip. `True` uses a per-account file derived from the email hash (each account gets its own file); a path string uses that exact file. Expired sessions automatically fall back to a full login. |

```python
from siakang import SiakangClient

client = SiakangClient(email, password,
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
| `detail` | `bool` | `False` | When `True`, every row also carries a `detail` object (see [get_detail](#get-detail)). Fetches all detail pages in parallel (up to [`PARALLEL_DETAIL_WORKERS`](#constants)) — measured ~2.9x faster than sequential. |

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
    "schedule_id": "019bde9b-...",    # offering UUID — key for get_detail
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
detail = client.get_detail(sid, tab_keys=["peserta"]) # header + peserta only
detail = client.get_detail(sid, tab_keys=["jurnal_perkuliahan"],
                           kuliah_id="019bde9b-...")   # a specific meeting
```

Where do I get a `schedule_id`? From any row of
[`get_schedule()`](#get-schedule) — it's the `"schedule_id"` field.

`tab_keys` picks which tabs to fetch (default `None` = all). The header card is
always fetched. Valid keys: `rps_bahan_ajar`, `peserta`,
`jurnal_perkuliahan`, `rekap_jurnal_perkuliahan` (also exported as
`siakang.TABS`).

`kuliah_id` re-selects the meeting on the Jurnal tab. Get ids from the tab's
own `pertemuan` list (first fetch without `kuliah_id`, then pick an id).

**Returns:**

```python
{
    "url": "https://siakang.untirta.ac.id/jadwal_perkuliahan/detail/<id>",
    "header": {
        "kode_jadwal": "2600000001",
        "mata_kuliah": "Mata Kuliah Satu",
        "kelas": "A24",
        "dosen": "Dosen Dummy, S.T., M.T.I",
        "ruang_dan_waktu": "Ruang Kuliah Contoh 101, Senin 09:10 - 10:50",
        "pertemuan_terlaksana": "0 Kali",
    },
    "tabs": {
        "rps_bahan_ajar":            { "sections": {...}, "error": None },
        "peserta":                   { "rows": [...], "error": None },
        "jurnal_perkuliahan":        { "rows": [...], "pertemuan": [...], "topik": "...", "rps_materi": "...", "error": None },
        "rekap_jurnal_perkuliahan":  { "rows": [...], "error": None },
    }
}
```

Each tab contains:

- `rows` — flat list of record dicts; every HTML table in the tab is merged
  into one list, each dict mapping snake_cased header → cell value, e.g.
  `[{"no": "1", "nama": "MAHASISWA CONTOH", "wali_setuju": "Ya", ...}]`.
- `error` — set only when the Siakang server itself failed to render the tab;
  the rest of the response stays usable.

### RPS & Bahan Ajar (`rps_bahan_ajar`)

This tab is a page with four named sections instead of a single table, so it
uses a `sections` map keyed by the section's `<h4>` heading (snake_cased).
Every section is always present, even when empty. Tables inside become
records; non-table content (download link cards) becomes
`{"judul": ..., "url": ...}` rows. `belum_rps` is `true` when the schedule has
no RPS yet (the site shows a "Jadwal ini belum memiliki RPS" alert and an
empty `daftar_rps` section).

```python
{
    "bahan_ajar":    [ {"judul": "Konsep Resiko", "url": ""} ],
    "rps_materi":    [ {"no": "1", "cpmk": "...", "materi": "...", "metode_penyampaian": "...", "alokasi_waktu": "..."} ],
    "evaluasi_aspek":[ {"no": "1", "aspek_evaluasi": "Aktivitas Partisipatif", "rencana_evaluasi": "...", "bobot": "50"} ],
    "rps_referensi": [ {"no": "1", "referensi": "G. Stoneburner, ..."} ],
    "belum_rps": False,
}
```

### Jurnal Perkuliahan (`jurnal_perkuliahan`)

Attendance here is a radio group (Hadir / Izin / Sakit / Tanpa Alasan); the
selected option is reported. Keterangan is `"-"` until a lecturer fills it in.
The tab also carries the meeting picker, the lecture topic and the RPS Materi
selection (both set by the lecturer, empty until then).

```python
{
    "pertemuan": [                       # meeting picker options
        {"id": "", "label": "-- Pilih Pertemuan"},
        {"id": "019bde9b-...", "label": "Senin, PK. 09:10 - 10:50 || Ruang ..."},
    ],
    "kuliah_id": "",                     # selected meeting ('' = picker default)
    "topik": "",                         # lecture topic text
    "rps_materi": "",                    # selected RPS Materi label
    "rows": [{
        "no": "1",
        "nama": "MAHASISWA CONTOH",
        "nim": "3337000001",
        "status_registrasi": "Aktif",
        "status_kehadiran": "Tanpa Alasan",   # one of Hadir / Izin / Sakit / Tanpa Alasan
        "keterangan": "-",
    }],
}
```

Pass `kuliah_id=<id from pertemuan>` to `get_detail` to re-render the
attendance table for that meeting.

::: tip detail=True shortcut
Instead of looping manually, call
`client.get_schedule(detail=True)` once — every schedule row then already
contains its own `detail` object.
:::

## Constants

| Name | Value | Meaning |
|---|---|---|
| `BASE` | `"https://siakang.untirta.ac.id"` | Root URL every request is built from. |
| `TABS` | see source | Detail-page tab keys accepted by `get_detail(tab_keys=...)`. |
| `PARALLEL_DETAIL_WORKERS` | `4` | Max parallel fetches inside `get_schedule(detail=True)`. Kept low on purpose — more (e.g. 8) is faster but trips Siakang's WAF (HTTP 520 / temporary block). |

## Errors

Every failure raises a subclass of `SiakangError`:

| Exception | Meaning |
|---|---|
| `SiakangAuthError` | Wrong email/password, or the session expired mid-run |
| `SiakangNotFoundError` | The requested semester doesn't exist |
| `SiakangUpstreamError` | Siakang server misbehaved or changed; usually retry later |

See [Errors & Responses](./errors-and-responses) for turning these into clean
API responses automatically.
