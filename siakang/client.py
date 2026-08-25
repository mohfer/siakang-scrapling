"""HTTP client for Siakang Untirta.

All Livewire interactions are performed directly against /livewire/update.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape

from curl_cffi import requests as cffi_requests
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


_NIM_RE = re.compile(r"^(.*\S)\s+(\d{8,})$")


def _split_peserta_nim(tables: list[dict]) -> list[dict]:
    """Split 'Nama 3337000001' cells into separate Nama / NIM columns."""
    for t in tables:
        if "Nama" not in t["headers"]:
            continue
        i = t["headers"].index("Nama")
        if i + 1 >= len(t["headers"]) or t["headers"][i + 1] != "NIM":
            t["headers"].insert(i + 1, "NIM")
        for r in t["rows"]:
            if i >= len(r):
                continue
            m = _NIM_RE.match(r[i])
            name, nim = (m.group(1), m.group(2)) if m else (r[i], "")
            r[i:i + 1] = [name, nim]
    return tables


def _parse_tables(html: str) -> list[dict]:
    """Extract every HTML table as a list of {headers, rows}."""
    tables = []
    for t in Selector(html).css("table"):
        headers = [_clean(th) for th in t.css("th")]
        rows = [
            [_clean(td) for td in tr.css("td")]
            for tr in t.css("tbody tr")
        ]
        rows = [r for r in rows if any(r)]
        if headers or rows:
            tables.append({"headers": headers, "rows": rows})
    return tables


class SiakangClient:
    def __init__(self, email: str, password: str, cache=None, max_workers: int = 4):
        """
        cache: object exposing get(key)/set(key, value); default None (no caching).
               See siakang.cache.FileCache; swap in Redis/DB for production.
        """
        self.email = email
        self.password = password
        self.cache = cache
        self.max_workers = max_workers
        self._session = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self):
        self._session = FetcherSession().__enter__()
        try:
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
        except SiakangError:
            self._session.__exit__(None, None, None)  # don't leak the session
            raise
        return self

    def __exit__(self, *exc):
        if self._session is not None:
            return self._session.__exit__(*exc)
        return False

    # -- low level -----------------------------------------------------------

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

    def _hydrate_lazy(self, url: str, segment: str, depth: int = 0) -> dict[str, str]:
        """Run __lazyLoad commits for every lazy component inside an html fragment.

        Each trigger belongs to the nearest preceding wire:snapshot element.
        Lazy renders may themselves contain further lazy children, so this
        recurses (bounded by depth). Returns {component name: concatenated html}.
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
            if not owner_sn:
                continue
            try:
                child_html = self._wire_commit(
                    url, owner_sn, calls=[{"method": "__lazyLoad", "params": [b64]}]
                )
            except SiakangUpstreamError:
                # one broken component must not sink the whole page
                continue
            # the fresh render may contain another level of lazy components
            parts = [child_html]
            parts.extend(self._hydrate_lazy(url, child_html, depth + 1).values())
            prev = rendered.get(owner_name)
            rendered[owner_name] = "\n".join([prev, *parts]) if prev else "\n".join(parts)
        return rendered

    def _wire_commit(self, url: str, snapshot: str, updates: dict | None = None,
                     calls: list | None = None) -> str:
        """Single-component livewire commit; returns the rendered html."""
        payload = {
            "_token": getattr(self, "_csrf", ""),
            "components": [{
                "snapshot": snapshot,
                "updates": updates or {},
                "calls": calls or [],
            }],
        }
        resp = self._session.post(
            f"{BASE}/livewire/update",
            json=payload,
            headers={"referer": url, "X-CSRF-TOKEN": payload["_token"]},
        )
        if resp.status != 200:
            raise SiakangUpstreamError(f"livewire/update HTTP {resp.status}")
        text = resp.body.decode() if isinstance(getattr(resp, "body", None), bytes) else str(resp.html_content)
        return "\n".join(c["effects"].get("html", "") for c in json.loads(text)["components"])

    @staticmethod
    def _lazy_load_calls(raw: str) -> dict[int, str]:
        """Find Livewire lazy-load mount params per document position.

        Lazy components carry their mount params as a base64-encoded
        ``__mountParamsContainer`` snapshot inside ``$wire.__lazyLoad('...')``.
        Returns {position in html: base64 params}.
        """
        out = {}
        for m in re.finditer(r'__lazyLoad\(([\'"])([A-Za-z0-9+/=]+)\1\)', raw):
            out[m.start()] = m.group(2)
        return out

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
        if resp.status != 200:
            raise SiakangUpstreamError(f"livewire/update HTTP {resp.status}")
        text = resp.body.decode() if isinstance(getattr(resp, "body", None), bytes) else str(resp.html_content)
        return {
            json.loads(c["snapshot"])["memo"]["name"]: c["effects"].get("html", "")
            for c in json.loads(text)["components"]
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

        self._fill_class(courses)

        if detail:
            for c in courses:
                c["detail"] = self.get_detail(c["schedule_id"])

        return courses

    def get_detail(self, schedule_id: str) -> dict:
        """Full detail page for one course offering: header + every tab."""
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
            key = _strip_tags(m.group(1))
            value = _strip_tags(re.split(r"<h5|</div>", m.group(2))[0])
            if key:
                header[key] = value

        tabs = {}
        for tab in TABS:
            entry = {"tables": [], "text": "", "error": None}
            try:
                resp = self._wire_update(href, [snaps["pengajaran.manajemen-kuliah"]], [{"active_menu": tab}])
                html = resp.get("pengajaran.manajemen-kuliah", "")

                if tab == "peserta":
                    content_html = peserta_html
                else:
                    # tab content is a lazy child component: run its __lazyLoad commit
                    children = self._hydrate_lazy(href, html)
                    content_html = "\n".join(children.values()) if children else html
                content_html = re.sub(r"<script.*?</script>", "", content_html, flags=re.S)
                entry["tables"] = _split_peserta_nim(_parse_tables(content_html))
                entry["text"] = _strip_tags(content_html)
            except SiakangError as e:
                entry["error"] = str(e)
            tabs[tab] = entry
        return {"url": href, "header": header, "tabs": tabs}

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
                "class": "",
                "schedule_id": links[0].attrib["href"].rsplit("/", 1)[-1] if links else "",
            })
        return courses

    def _fetch_one_class(self, cookies: dict, href: str) -> tuple[str, str]:
        key = href.rsplit("/", 1)[-1]
        class_letter = ""
        sess = cffi_requests.Session(impersonate="chrome", cookies=cookies)
        try:
            r = sess.get(href, headers={"referer": f"{BASE}/jadwal_perkuliahan"})
            csrf_m = re.search(r'data-csrf="([^"]+)"', r.text)
            if csrf_m:
                csrf = csrf_m.group(1)
                payload = {"_token": csrf, "components": [
                    {"snapshot": sn, "updates": {}, "calls": []} for sn in self._wire_snapshots(r.text)
                ]}
                resp = sess.post(
                    f"{BASE}/livewire/update",
                    json=payload,
                    headers={"referer": href, "X-CSRF-TOKEN": csrf},
                )
                # transient server errors happen; treat as cache miss instead of crashing
                if resp.status == 200:
                    for comp in resp.json().get("components", []):
                        m = re.search(r"Kelas</h5>(.*?)<br>", comp["effects"].get("html", ""), re.S)
                        if m:
                            class_letter = " ".join(re.sub(r"<[^>]+>", " ", m.group(1)).split())
                            break
        except Exception:
            pass  # leave class_letter empty; the cache simply stays a miss
        finally:
            sess.close()
        return key, class_letter

    def _fill_class(self, courses: list[dict]):
        todo, results = [], {}
        if self.cache:
            for c in courses:
                val = self.cache.get(c["schedule_id"]) if c["schedule_id"] else None
                if val is not None:
                    c["class"] = val
                elif c["schedule_id"]:
                    todo.append(c)
        else:
            todo = [c for c in courses if c["schedule_id"]]

        if todo:
            cookies = self._session._curl_session.cookies.get_dict()
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                urls = [f"{BASE}/jadwal_perkuliahan/detail/{c['schedule_id']}" for c in todo]
                for key, class_letter in ex.map(lambda u: self._fetch_one_class(cookies, u), urls):
                    results[key] = class_letter
            for c in todo:
                c["class"] = results.get(c["schedule_id"], "")
                if self.cache and c["class"]:
                    self.cache.set(c["schedule_id"], c["class"])
