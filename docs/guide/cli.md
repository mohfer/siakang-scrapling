# CLI Examples

Ready-made command line tools live in `examples/`. They read credentials from a
`.env` file in the project root:

```dotenv
EMAIL=xxx@student.untirta.ac.id
PASSWORD=...
# optional — leave empty to use the account's active semester
SEMESTER=20252
```

## scrape_schedule.py

Class schedule from `/jadwal_perkuliahan`.

```bash
uv run python examples/scrape_schedule.py                    # one line per course
uv run python examples/scrape_schedule.py --json             # full JSON envelope
uv run python examples/scrape_schedule.py --semester 20252   # pick a semester
uv run python examples/scrape_schedule.py --detail --json    # incl. detail pages (slow)
```

## scrape_grades.py

Study results from `/hasil-studi`.

```bash
uv run python examples/scrape_grades.py                      # IP/IPK + one line per course
uv run python examples/scrape_grades.py --semester 20251
uv run python examples/scrape_grades.py --json
```

`score`, `letter`, `ip` and `ipk` are `null` until lecturers publish the grades.

## scrape_semester.py

Semester list from `/dashboard/list-semester`.

```bash
uv run python examples/scrape_semester.py
```

## scrape_schedule_browser.py

Fallback that drives a real Camoufox browser. Only useful if the plain-HTTP path
ever gets blocked; it is slower and heavier. Requires the same `.env`.

```bash
uv run python examples/scrape_schedule_browser.py
```
