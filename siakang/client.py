"""HTTP client for Siakang Untirta.

All Livewire interactions are performed directly against /livewire/update.
"""

import hashlib
import json
import re
from html import unescape
from pathlib import Path

from scrapling.fetchers import FetcherSession
from scrapling.parser import Selector

BASE = "https://siakang.untirta.ac.id"

TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}")
TABS = ["rps_bahan_ajar", "peserta", "jurnal_perkuliahan", "rekap_jurnal_perkuliahan"]


class SiakangError(Exception):
    """Base error for all siakang failures."""


class SiakangAuthError(SiakangError):
    """Login failed or session no longer valid."""


class SiakangNotFoundError(SiakangError):
    """A requested resource (e.g. semester) does not exist."""


class SiakangUpstreamError(SiakangError):
    """The Siakang server returned an unexpected response."""


def _clean(el_or_str) -> str:
    """Collapse consecutive whitespace into single spaces."""
    if hasattr(el_or_str, "get_all_text"):
        el_or_str = el_or_str.get_all_text()
    return " ".join(str(el_or_str).split())


def _strip_tags(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_snake(key: str) -> str:
    """snake_case a human heading: 'Wali Setuju' -> 'wali_setuju',
    'RPS Referensi' -> 'rps_referensi', 'Ruang dan Waktu' -> 'ruang_dan_waktu'."""
    words = re.findall(r"[A-Za-z0-9]+", key)
    return "_".join(words).lower()


_NIM_RE = re.compile(r"^(.*\S)\s+(\d{8,})$")


def _split_peserta_nim(tables: list[list[dict]]) -> list[list[dict]]:
    """Split 'Nama 3337000001' cells into nama / nim keys and keep nim
    directly after nama in every table that has both."""
    for table in tables:
        if not any("nim" in row for row in table):
            split = False
            for row in table:
                m = _NIM_RE.match(row.get("nama", ""))
                if m and m.group(2):
                    row["nama"] = m.group(1)
                    row["nim"] = m.group(2)
                    split = True
            if split and any("nama" in row for row in table):
                for row in table:
                    row.setdefault("nim", "")
        for i, row in enumerate(table):
            if "nama" in row and "nim" in row:
                keys = [k for k in row if k != "nim"]
                keys.insert(keys.index("nama") + 1, "nim")
                table[i] = {k: row[k] for k in keys}
    return tables


def _parse_tables(html: str) -> list[list[dict]]:
    """Extract every HTML table as a list of records (list of row dicts)."""
    tables = []
    for t in Selector(html).css("table"):
        headers = [_clean(th) for th in t.css("th")]
        rows = [
            [_clean(td) for td in tr.css("td")]
            for tr in t.css("tbody tr")
        ]
        rows = [r for r in rows if any(r)]
        records = [dict(zip([_to_snake(h) for h in headers], row)) for row in rows] if headers else [
            {"value": r[0]} for r in rows]
        if records:
            tables.append(records)
    return tables


def _parse_jurnal(html: str) -> list[dict]:
    """Parse the Jurnal Perkuliahan table, where attendance is a radio group.

    Status Kehadiran is a row of four radios (Hadir/Izin/Sakit/Tanpa Alasan);
    the selected one is the ``checked`` radio. Keterangan is a free-text cell
    that shows ``-`` by default. Other columns keep their visible text.
    """
    rows = []
    for tr in Selector(html).css("tbody tr"):
        tds = tr.css("td")
        if len(tds) < 5:
            continue
        checked = tr.css('input[type="radio"]:checked')
        status = ""
        if checked:
            radio_id = checked[0].attrib.get("id", "")
            for lbl in tr.css("label"):
                if lbl.attrib.get("for") == radio_id:
                    status = _clean(lbl)
                    break
        keterangan = _clean(tds[-1])
        rows.append({
            "no": _clean(tds[0]),
            "nama": _clean(tds[1].css("h5")[0]) if tds[1].css("h5") else _clean(tds[1]),
            "nim": _clean(tds[1].css(".badge")[0]) if tds[1].css(".badge") else "",
            "status_registrasi": _clean(tds[2].css(".badge")[0]) if tds[2].css(".badge") else _clean(tds[2]),
            "status_kehadiran": status or "-",
            "keterangan": keterangan or "-",
        })
    return rows


def _parse_jurnal_meta(html: str) -> dict:
    """Extract the dropdowns/textarea at the top of the Jurnal tab.

    ``pertemuan`` lists every meeting option {id, label}; ``kuliah_id`` is the
    selected one ('' = "Pilih Pertemuan"). ``topik`` is the lecture topic text
    and ``rps_materi`` the selected RPS Materi label — both are set by the
    lecturer, so they may be empty.
    """
    sel = Selector(html)
    meta: dict = {"pertemuan": [], "kuliah_id": "", "topik": "", "rps_materi": ""}

    p_sel = sel.css('select[wire\\:model\\.live="kuliah_id"]')
    if p_sel:
        meta["pertemuan"] = [{"id": o.attrib.get("value", ""), "label": _clean(o)}
                             for o in p_sel[0].css("option")]
        meta["kuliah_id"] = p_sel[0].css('option[selected]')[0].attrib.get("value", "") \
            if p_sel[0].css('option[selected]') else ""

    topik = sel.css('textarea[wire\\:model="topik"]')
    if topik:
        meta["topik"] = _clean(topik[0])

    rps = sel.css('select[wire\\:model="rps_materi_id"] option[selected]')
    if rps:
        meta["rps_materi"] = _clean(rps[0])
    return meta


def _parse_rps_sections(html: str) -> dict[str, list[dict]]:
    """Split the RPS & Bahan Ajar tab into its named sections (h4 headings).

    Every ``<h4 class="header-title">`` heading opens a section. Tables inside
    become records; non-table content (Bahan Ajar link cards) becomes records
    too. Sections stay present even when empty (empty list).
    """
    sections: dict[str, list[dict]] = {}
    parts = re.split(r'<h4[^>]*class="header-title"[^>]*>(.*?)</h4>', html, flags=re.S)
    for i in range(1, len(parts), 2):
        name = _to_snake(_strip_tags(parts[i]))
        body = parts[i + 1]
        if not name or name in sections:
            continue
        tables = _parse_tables(body)
        if Selector(body).css("table"):
            sections[name] = [row for t in tables for row in t]
            continue
        records = [{"judul": _clean(a), "url": a.attrib.get("href", "")}
                   for a in Selector(body).css("a")]
        # each card carries a title link plus an icon-only download link; drop the empties
        records = [r for r in records if r["judul"]]
        if not records:
            text = _strip_tags(body)
            if text:
                records = [{"value": text}]
        sections[name] = records
    return sections


class SiakangClient:
    def __init__(self, email: str, password: str,
                 session_file: str | Path | bool | None = None):
        """
        session_file: persist login cookies so later runs skip the login round-trip.
               True  -> default path derived from the email hash, so each account
                        gets its own file and sessions never collide.
               path  -> that exact file (shared across accounts = they overwrite
                        each other; don't do that for different accounts).
               None  -> disabled (default).
               The file holds a bearer credential — keep it out of git.
        """
        self.email = email
        self.password = password
        self.session_file = session_file
        self._session = None

    # -- lifecycle ---------------------------------------------------------

    def _session_cookie_path(self) -> Path:
        if self.session_file is True:
            digest = hashlib.sha1(self.email.encode()).hexdigest()[:10]
            return Path(f".siakang_session_{digest}.json")
        return Path(self.session_file)

    def _restore_session(self) -> bool:
        """Load saved cookies and verify they still authenticate us."""
        try:
            cookies = json.loads(self._session_cookie_path().read_text())
            jar = self._session._curl_session.cookies
            for name, value in cookies.items():
                jar.set(name, value)
            r = self._session.get(f"{BASE}/dashboard/dashboard-akademik")
        except Exception:
            return False
        ok = r.status == 200 and "/auth/login" not in str(getattr(r, "url", ""))
        if ok:
            m = re.search(r'data-csrf="([^"]+)"', getattr(r, "html_content", ""))
            if m:
                self._csrf = m.group(1)
        return ok

    def _save_session(self):
        path = self._session_cookie_path()
        path.write_text(json.dumps(self._session._curl_session.cookies.get_dict()))
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def __enter__(self):
        self._session = FetcherSession().__enter__()
        try:
            if self.session_file and self._restore_session():
                return self
            page = self._session.get(f"{BASE}/auth/login")
            tokens = page.css('input[name="_token"]')
            if not tokens:
                raise SiakangUpstreamError("Failed to open login page (CSRF token not found)")
            self._session.post(
                f"{BASE}/auth/login",
                data={"_token": tokens[0].attrib["value"], "email": self.email, "password": self.password},
            )
            r = self._session.get(f"{BASE}/dashboard/dashboard-akademik")
            # a failed login lands back on the login page with HTTP 200
            if r.status != 200 or "auth/login" in str(getattr(r, "url", "")):
                raise SiakangAuthError("Login failed — check email/password")
            if self.session_file:
                self._save_session()
        except SiakangError:
            self._session.__exit__(None, None, None)  # don't leak the session
            raise
        return self

    def __exit__(self, *exc):
        if self._session is not None:
            return self._session.__exit__(*exc)
        return False

    # -- low level -----------------------------------------------------------

    @staticmethod
    def _resp_status(resp) -> int:
        """HTTP status across scrapling and raw curl_cffi responses."""
        return getattr(resp, "status", None) or resp.status_code

    @staticmethod
    def _resp_text(resp) -> str:
        """Body text across scrapling and raw curl_cffi responses."""
        body = getattr(resp, "body", None)
        if isinstance(body, bytes):
            return body.decode()
        html_content = getattr(resp, "html_content", None)
        if html_content is not None:
            return html_content
        return resp.text

    def _get_page(self, url: str, referer: str) -> str:
        if self._session is None:
            raise SiakangError("Client is not open — use 'with SiakangClient(...) as client:'")
        raw = ""
        for attempt in (1, 2):  # Cloudflare occasionally interjects a challenge page; retry once
            r = self._session.get(url, headers={"referer": referer})
            if r.status != 200:
                raise SiakangUpstreamError(f"HTTP {r.status} on {url}")
            raw = r.html_content
            landed_on_login = "/auth/login" in str(getattr(r, "url", ""))
            challenged = "challenge-platform" in raw[:5000]
            if not landed_on_login and not challenged:
                break
            if attempt == 2:
                raise SiakangUpstreamError(f"Repeated challenge / session redirect while fetching {url}")
            import time as _time
            _time.sleep(1)
        m = re.search(r'data-csrf="([^"]+)"', raw)
        if m:
            self._csrf = m.group(1)
        return raw

    @staticmethod
    def _wire_snapshots(raw: str) -> list[str]:
        # Livewire picks the attribute delimiter based on content (double quotes
        # inside the JSON force single-quoted attributes), so match either.
        pairs = re.findall(r'wire:snapshot=(["\'])(.*?)\1', raw, re.S)
        return [unescape(value) for _, value in pairs]

    @staticmethod
    def _lazy_load_markers(raw: str) -> dict[int, str]:
        """Locate Livewire lazy-load triggers: ``$wire.__lazyLoad('<b64>')``.

        Returns {position in html: base64 mount params}. The surrounding quotes
        may appear literally or HTML-escaped (&#039;) depending on context.
        """
        return {m.start(): m.group(1)
                for m in re.finditer(r'__lazyLoad\((?:&#039;|&quot;|[\x27\x22])([A-Za-z0-9+/=]+)(?:&#039;|&quot;|[\x27\x22])\)', raw)}

    def _hydrate_lazy(self, url: str, segment: str, depth: int = 0,
                      session=None, token: str | None = None, owner: str | None = None) -> dict[str, str]:
        """Run __lazyLoad commits for every lazy component inside an html fragment.

        Each trigger belongs to the nearest preceding wire:snapshot element.
        Lazy renders may themselves contain further lazy children, so this
        recurses (bounded by depth). Returns {component name: concatenated html}.
        owner: only hydrate markers whose owning component has this name.
        """
        rendered = {}
        if depth > 4 or not segment:
            return rendered

        comps = [
            (m.start(), json.loads(unescape(m.group(2)))["memo"]["name"], unescape(m.group(2)))
            for m in re.finditer(r'wire:snapshot=(["\'])(.*?)\1', segment, re.S)
        ]
        for lpos, b64 in self._lazy_load_markers(segment).items():
            owner_name = owner_sn = None
            for pos, name, sn in comps:
                if pos < lpos:
                    owner_name, owner_sn = name, sn
                else:
                    break
            if not owner_sn or (owner and owner_name != owner):
                continue
            try:
                child_html = self._wire_commit(
                    url, owner_sn, calls=[{"method": "__lazyLoad", "params": [b64]}],
                    session=session, token=token,
                )
            except SiakangUpstreamError:
                # one broken component must not sink the whole page
                continue
            # the fresh render may contain another level of lazy components
            parts = [child_html]
            parts.extend(self._hydrate_lazy(url, child_html, depth + 1, session=session, token=token).values())
            prev = rendered.get(owner_name)
            rendered[owner_name] = "\n".join([prev, *parts]) if prev else "\n".join(parts)
        return rendered

    def _wire_commit(self, url: str, snapshot: str, updates: dict | None = None,
                     calls: list | None = None, session=None, token: str | None = None,
                     return_snapshots: bool = False) -> str | tuple[str, dict[str, str]]:
        """Single-component livewire commit; returns the rendered html.

        return_snapshots: also return {component name: fresh snapshot string}
        for every component in the response (usable for follow-up commits).
        """
        payload = {
            "_token": token if token is not None else getattr(self, "_csrf", ""),
            "components": [{
                "snapshot": snapshot,
                "updates": updates or {},
                "calls": calls or [],
            }],
        }
        resp = (session or self._session).post(
            f"{BASE}/livewire/update",
            json=payload,
            headers={"referer": url, "X-CSRF-TOKEN": payload["_token"]},
        )
        if self._resp_status(resp) != 200:
            raise SiakangUpstreamError(f"livewire/update HTTP {self._resp_status(resp)}")
        comps = json.loads(self._resp_text(resp))["components"]
        html = "\n".join(c["effects"].get("html", "") for c in comps)
        if return_snapshots:
            snaps = {json.loads(c["snapshot"])["memo"]["name"]: c["snapshot"] for c in comps}
            return html, snaps
        return html

    def _wire_update(self, url: str, snapshots: list[str], updates_list: list[dict]) -> dict[str, str]:
        """POST /livewire/update. Returns {component name: rendered html}."""
        payload = {
            "_token": getattr(self, "_csrf", ""),
            "components": [
                {"snapshot": sn, "updates": upd, "calls": []}
                for sn, upd in zip(snapshots, updates_list)
            ],
        }
        resp = self._session.post(
            f"{BASE}/livewire/update",
            json=payload,
            headers={"referer": url, "X-CSRF-TOKEN": payload["_token"]},
        )
        if self._resp_status(resp) != 200:
            raise SiakangUpstreamError(f"livewire/update HTTP {self._resp_status(resp)}")
        return {
            json.loads(c["snapshot"])["memo"]["name"]: c["effects"].get("html", "")
            for c in json.loads(self._resp_text(resp))["components"]
        }

    # -- semesters -------------------------------------------------------------

    def list_semesters(self) -> list[dict]:
        """All semesters as [{code, name, id, active}, ...]"""
        semesters = []
        url = f"{BASE}/dashboard/list-semester"
        current_page = 1
        seen = set()
        while url and url not in seen:
            seen.add(url)
            raw = self._get_page(url, f"{BASE}/dashboard")
            html = Selector(raw)
            for card in html.css(".card-body"):
                titles = card.css("h5.card-title")
                links = [a for a in card.css('a[href*="change-semester"]')]
                if not (titles and links):
                    continue
                kode_els = card.css("p.card-text")
                mk = re.search(r"#(\d+)", kode_els[0].text if kode_els else "")
                mu = re.search(r"change-semester/([\w-]+)", links[0].attrib.get("href", ""))
                semesters.append({
                    "code": mk.group(1) if mk else "",
                    "name": _clean(titles[0]),
                    "id": mu.group(1) if mu else "",
                    "active": bool(card.css(".bi-check2-circle")),
                })

            # only follow pagination links pointing past the current page
            nxt = None
            for a in html.css('.pagination a[href*="list-semester?page="]'):
                m = re.search(r"page=(\d+)", a.attrib.get("href", ""))
                if m and int(m.group(1)) > current_page:
                    nxt, next_num = a.attrib["href"], int(m.group(1))
                    break
            if nxt:
                url, current_page = nxt, next_num
            else:
                url = None
        return semesters

    # -- grades ---------------------------------------------------------------

    def get_grades(self, semester: str | None = None) -> dict:
        """Study results from /hasil-studi.

        semester: semester code (e.g. '20251'). None = whatever semester is
                currently selected in this session (the account's active one on a
                fresh login).
        Nilai/Mutu/IP/IPK are empty until the lecturer publishes the grades.

        Returns {"ip": float | None, "ipk": float | None, "courses": [...]}
        where each course has: no, schedule_code, name, code, credits,
        lecturers, score, letter.
        """
        if semester is not None:
            target = next((s for s in self.list_semesters() if s["code"] == semester), None)
            if not target:
                raise SiakangNotFoundError(f"Semester {semester} not found")
            self._session.get(
                f"{BASE}/dashboard/change-semester/{target['id']}",
                headers={"referer": f"{BASE}/dashboard/list-semester"},
            )

        raw = self._get_page(f"{BASE}/hasil-studi", f"{BASE}/dashboard/dashboard-akademik")
        html = Selector(raw)

        courses = []
        for t in html.css("table"):
            headers = [_clean(th).lower() for th in t.css("th")]
            if "nilai" not in headers:
                continue
            for tr in t.css("tbody tr"):
                cells = [_clean(td) for td in tr.css("td")]
                if len(cells) < 6 or not cells[0].isdigit():
                    continue  # skip the IP/IPK summary rows inside tbody
                m = re.match(r"(.+?) \(([A-Z]+\d+)\) (\d+) SKS", cells[2])
                courses.append({
                    "no": int(cells[0]),
                    "schedule_code": cells[1],
                    "name": m.group(1) if m else cells[2],
                    "code": m.group(2) if m else "",
                    "credits": int(m.group(3)) if m else None,
                    "lecturers": [p.strip() for p in re.split(r"\s*\d+\.\s*", cells[3]) if p.strip()],
                    "score": _to_float(cells[4]),
                    "letter": cells[5] or None,
                })

        ip_m = re.search(r"IP\s*:\s*<span>([^<]*)</span>", raw)
        ipk_m = re.search(r"IPK\s*:\s*<span>([^<]*)</span>", raw)
        return {
            "ip": _to_float(ip_m.group(1)) if ip_m else None,
            "ipk": _to_float(ipk_m.group(1)) if ipk_m else None,
            "courses": courses,
        }

    # -- schedule ---------------------------------------------------------------

    def get_schedule(self, semester: str | None = None, detail: bool = False) -> list[dict]:
        """The student's class schedule.

        semester: semester code (e.g. '20261'). None = account's active semester.
        detail: when True each row gains a 'detail' field containing the full
                course-detail page (header + all tabs). Much slower — one extra
                page per course.

        Returns a list of dicts; see README for the exact shape.
        """
        if semester is not None:
            target = next((s for s in self.list_semesters() if s["code"] == semester), None)
            if not target:
                raise SiakangNotFoundError(f"Semester {semester} not found")
            self._session.get(
                f"{BASE}/dashboard/change-semester/{target['id']}",
                headers={"referer": f"{BASE}/dashboard/list-semester"},
            )

        raw = self._get_page(f"{BASE}/jadwal_perkuliahan", f"{BASE}/dashboard/dashboard-akademik")
        names = {}
        for sn in self._wire_snapshots(raw):
            d = json.loads(sn)
            names[d["memo"]["name"]] = sn
        missing = [n for n in ("jadwal.toggle-jadwal", "mahasiswa.jadwal-mahasiswa") if n not in names]
        if missing:
            raise SiakangUpstreamError(f"Livewire components changed / not found: {missing}")

        # switch the page to list view via direct Livewire property updates
        html_map = self._wire_update(
            f"{BASE}/jadwal_perkuliahan",
            [names["jadwal.toggle-jadwal"], names["mahasiswa.jadwal-mahasiswa"]],
            [{"selected": "card"}, {"mode": "card"}],
        )
        courses = self._parse_cards(Selector(html_map["mahasiswa.jadwal-mahasiswa"]))
        if not courses:
            raise SiakangUpstreamError("No schedule cards found — list view switch failed?")

        if detail:
            for c in courses:
                c["detail"] = self.get_detail(c["schedule_id"])

        return courses

    def get_detail(self, schedule_id: str, tab_keys: list[str] | None = None,
                   kuliah_id: str | None = None) -> dict:
        """Full detail page for one course offering: header + selected tabs.

        tab_keys: tab keys to fetch; None = all tabs (see TABS). The header
                  card is always fetched. Fetched tabs still appear under
                  their key.
        kuliah_id: Jurnal tab meeting id (from the tab's ``pertemuan`` list).
                  None = the default "Pilih Pertemuan" state. Setting it
                  re-renders that meeting's attendance table.
        """
        href = f"{BASE}/jadwal_perkuliahan/detail/{schedule_id}"
        raw = self._get_page(href, f"{BASE}/jadwal_perkuliahan")

        snaps = {}
        for sn in self._wire_snapshots(raw):
            d = json.loads(sn)
            snaps[d["memo"]["name"]] = sn
        if "pengajaran.manajemen-kuliah" not in snaps:
            raise SiakangUpstreamError("Livewire component changed / not found: pengajaran.manajemen-kuliah")

        # header & participants are lazy components; run their __lazyLoad commits
        rendered = self._hydrate_lazy(href, raw)
        header_html = rendered.get("pengajaran.detail-kuliah", "")
        peserta_html = rendered.get("jadwal.peserta", "")

        header = {}
        for part in re.split(r"<h5[^>]*>", header_html)[1:]:
            m = re.match(r"(.*?)</h5>(.*)", part, re.S)
            if not m:
                continue
            key = _to_snake(_strip_tags(m.group(1)))
            value = _strip_tags(re.split(r"<h5|</div>", m.group(2))[0])
            if key:
                header[key] = value

        tabs = {}
        for tab in (TABS if tab_keys is None else tab_keys):
            entry = {"error": None}
            try:
                resp = self._wire_update(href, [snaps["pengajaran.manajemen-kuliah"]], [{"active_menu": tab}])
                html = resp.get("pengajaran.manajemen-kuliah", "")

                if tab == "peserta":
                    content_html = peserta_html
                elif tab == "jurnal_perkuliahan" and kuliah_id:
                    content_html = self._render_jurnal_meeting(href, html, kuliah_id)
                else:
                    # tab content is a lazy child component: run its __lazyLoad commit
                    children = self._hydrate_lazy(href, html)
                    content_html = "\n".join(children.values()) if children else html
                content_html = re.sub(r"<script.*?</script>", "", content_html, flags=re.S)
                if tab == "rps_bahan_ajar":
                    entry["sections"] = _parse_rps_sections(content_html)
                elif tab == "jurnal_perkuliahan":
                    entry.update(_parse_jurnal_meta(content_html))
                    if kuliah_id:
                        entry["kuliah_id"] = kuliah_id
                    entry["rows"] = _parse_jurnal(content_html)
                else:
                    tables = _split_peserta_nim(_parse_tables(content_html))
                    entry["rows"] = [row for t in tables for row in t]
            except SiakangError as e:
                entry["error"] = str(e)
            tabs[tab] = entry
        return {"url": href, "header": header, "tabs": tabs}

    def _render_jurnal_meeting(self, href: str, jurnal_html: str, kuliah_id: str) -> str:
        """Select a Jurnal Perkuliahan meeting: mount the lazy journal component
        then update its ``kuliah_id`` property. Returns the re-rendered html."""
        comps = [
            (m.start(), unescape(m.group(2)))
            for m in re.finditer(r'wire:snapshot=(["\'])(.*?)\1', jurnal_html, re.S)
        ]
        markers = list(self._lazy_load_markers(jurnal_html).items())
        for lpos, b64 in markers:
            owner_sn = None
            for pos, sn in comps:
                if pos < lpos:
                    owner_sn = sn
                else:
                    break
            if not owner_sn:
                continue
            _, snaps = self._wire_commit(href, owner_sn,
                                         calls=[{"method": "__lazyLoad", "params": [b64]}],
                                         return_snapshots=True)
            if "pengajaran.jurnal-perkuliahan" in snaps:
                html, _ = self._wire_commit(href, snaps["pengajaran.jurnal-perkuliahan"],
                                            updates={"kuliah_id": kuliah_id},
                                            return_snapshots=True)
                return html
        return jurnal_html
    # -- parsing ---------------------------------------------------------------

    @staticmethod
    def _parse_cards(html) -> list[dict]:
        courses = []
        for card in html.css("div.card"):
            h5s = card.css("h5")
            links = card.css('a[href*="/detail/"]')
            if not h5s:
                continue
            bodies = card.css(".card-body")
            body = bodies[0] if bodies else card

            spans = [_clean(s) for s in body.css(".small span")]
            badges = body.css(".badge")

            schedules, lecturers = [], []
            for h6 in body.css("h6"):
                label = _clean(h6).upper()
                section = None
                for anc in h6.iterancestors():
                    lis = anc.css(".list-unstyled li")
                    if lis:
                        section = lis
                        break
                if not section:
                    continue
                if label.startswith("JADWAL"):
                    for li in section:
                        spans_li = [_clean(s) for s in li.css("span")]
                        entry = {"day": "", "time": "", "room": ""}
                        for sp in spans_li:
                            m = TIME_RE.search(sp)
                            words = sp.split()
                            if m and words:
                                # keep the day name exactly as Siakang provides it (Indonesian)
                                entry["day"] = words[0]
                                entry["time"] = m.group()
                            elif sp.lower().startswith("ruang"):
                                entry["room"] = sp
                        schedules.append(entry)
                elif label == "DOSEN PENGAMPU":
                    lecturers = [_clean(li) for li in section]

            credits_text = badges[0].get_all_text().split() if badges else []
            courses.append({
                "name": _clean(h5s[0]),
                "code": spans[0] if len(spans) > 0 else "",
                "schedule_code": spans[1] if len(spans) > 1 else "",
                "mode": spans[2].title() if len(spans) > 2 else "",
                "credits": int(credits_text[0]) if credits_text and credits_text[0].isdigit() else None,
                "schedules": schedules,
                "lecturers": lecturers,
                "schedule_id": links[0].attrib["href"].rsplit("/", 1)[-1] if links else "",
            })
        return courses
