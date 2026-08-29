# Getting Started

A gentle walkthrough: from zero to your first schedule data.

## 1. Install

```bash
uv add git+https://github.com/mohfer/siakang-scrapling
# or from a local copy:
uv add /path/to/siakang-scrapling
```

## 2. Prepare credentials

Create a `.env` file next to your script:

```dotenv
EMAIL=xxx@student.untirta.ac.id
PASSWORD=your-password-here
```

## 3. Fetch your schedule

```python
import os
from dotenv import load_dotenv
from siakang import SiakangClient

load_dotenv()

with SiakangClient(email=os.getenv("EMAIL"), password=os.getenv("PASSWORD")) as client:
    rows = client.get_schedule()

for row in rows:
    sesi = row["schedules"][0]
    print(f"{row['code']} {row['name']} — {sesi['day']} {sesi['time']}")
```

What happens here:

1. `SiakangClient(...)` stores your credentials.
2. Entering the `with` block logs you into Siakang (session cookies handled automatically).
3. `get_schedule()` opens *Jadwal Perkuliahan*, switches it to List View, and reads every course card.
4. Leaving the `with` block closes the session cleanly.

## 4. Pick a different semester

Every method that shows semester-dependent data accepts a `semester` code:

```python
rows = client.get_schedule(semester="20252")     # 2025/2026 Genap
grades = client.get_grades(semester="20251")     # 2025/2026 Gasal
```

Not sure which codes exist? Ask the library:

```python
for s in client.list_semesters():
    print(s["code"], "→", s["name"], "(active)" if s["active"] else "")
```

## 5. Want everything about one course?

```python
detail = client.get_detail(rows[0]["schedule_id"])
print(detail["header"])                          # kelas, dosen, ruang_dan_waktu, ...
print(detail["tabs"]["peserta"]["rows"])         # participant rows
```

## Next steps

- Wrap calls with [`@api_response`](./errors-and-responses) so your app always
  receives `{code, message, data}` instead of exceptions.
- Read [API Reference](./api-reference) for the complete field-by-field output.
