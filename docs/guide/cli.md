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
uv run python examples/scrape_schedule.py --detail --json    # incl. detail pages (parallel, ~3x faster than before)
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

## scrape_detail.py

Detail page for one course offering from `/jadwal_perkuliahan/detail/<id>`.

```bash
uv run python examples/scrape_detail.py                                     # peserta tab only (default)
uv run python examples/scrape_detail.py --schedule-id <uuid>                # a specific offering
uv run python examples/scrape_detail.py --tabs rps_bahan_ajar jurnal_perkuliahan
uv run python examples/scrape_detail.py --tabs jurnal_perkuliahan --kuliah-id <meeting-uuid>
uv run python examples/scrape_detail.py --json                              # full JSON envelope
```

`--tabs` defaults to `peserta`; pass the others (`rps_bahan_ajar`,
`jurnal_perkuliahan`, `rekap_jurnal_perkuliahan`) explicitly, or `--tabs
rps_bahan_ajar peserta jurnal_perkuliahan rekap_jurnal_perkuliahan` for
everything. `--kuliah-id` selects a specific meeting on the Jurnal tab (id from
that tab's `pertemuan` list).
