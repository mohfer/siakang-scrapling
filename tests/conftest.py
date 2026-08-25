"""Shared fixtures: HTML builders and a fake HTTP session (no real network)."""

import base64
import html
import json
from urllib.parse import urlparse

import pytest
from scrapling.parser import Selector

from siakang.client import BASE

CSRF = "test-csrf-token"


# ---------------------------------------------------------------- responses


class FakeResponse:
    """Minimal stand-in for scrapling's Response."""

    def __init__(self, body="", status=200, url=f"{BASE}/x", content_type="html"):
        self.status = status
        self.url = url
        if content_type == "json":
            self.body = body.encode() if isinstance(body, str) else body
            self.html_content = body if isinstance(body, str) else body.decode()
        else:
            self.html_content = body
            self.body = body.encode()

    def css(self, selector):
        return Selector(self.html_content).css(selector)


class FakeCurlCookies:
    def __init__(self):
        self._d = {"siakang_session": "abc123"}

    def set(self, name, value):
        self._d[name] = value

    def get_dict(self):
        return dict(self._d)


class FakeCurlSession:
    def __init__(self):
        self.cookies = FakeCurlCookies()


class FakeSession:
    """Routes requests through registered handlers and records every call.

    handlers: list of (method, url_predicate(url)->bool, handler(url, kwargs)->FakeResponse)
    """

    closed = False
    _curl_session = FakeCurlCookies()

    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []
        self._curl_session = FakeCurlSession()

    def get(self, url, headers=None, **kw):
        self.calls.append(("GET", url))
        kwargs = {"headers": headers, **kw}
        for method, pred, handler in self.handlers:
            if method == "GET" and pred(url):
                return handler(url, kwargs)
        raise AssertionError(f"unrouted GET {url}")

    def post(self, url, headers=None, **kw):
        self.calls.append(("POST", url))
        kwargs = {"headers": headers, **kw}
        for method, pred, handler in self.handlers:
            if method == "POST" and pred(url):
                return handler(url, kwargs)
        raise AssertionError(f"unrouted POST {url}")

    def _curl_session(self):  # pragma: no cover - never called as attribute this way
        pass

    @property
    def curl_session(self):
        return FakeCurlSession()

    def close(self):
        self.closed = True

    def __exit__(self, *exc):
        self.closed = True
        return False


class FakeFetcherSession:
    """Replaces scrapling's FetcherSession context manager in tests."""

    closed = False

    def __init__(self, inner):
        self.inner = inner

    def __enter__(self):
        return self.inner

    def __exit__(self, *exc):
        self.closed = True
        return False


# ---------------------------------------------------------------- html builders


def login_html(csrf=CSRF, with_token=True):
    token = '<input type="hidden" name="_token" value="LOGIN_TOKEN">' if with_token else ""
    return f'<html data-csrf="{csrf}"><title>Login - Siakang</title><body><form>{token}</form></body></html>'


def dashboard_html(csrf=CSRF):
    return f'<html data-csrf="{csrf}"><title>Dashboard - Siakang</title><body>ok</body></html>'


def semester_card(code, name, uuid, active=False):
    icon = '<i class="bi bi-check2-circle"></i>' if active else ""
    return (
        f'<div class="card-body"><h5 class="card-title">{icon} {name}</h5>'
        f'<p class="card-text">Kode Semester #{code}</p>'
        f'<a href="{BASE}/dashboard/change-semester/{uuid}" class="btn">Aktifkan</a></div>'
    )


def list_semesters_page(cards, next_page=None):
    page_links = ""
    if next_page:
        page_links = f'<a href="{BASE}/dashboard/list-semester?page={next_page}">2</a>'
    pagination = f'<div class="pagination">{page_links}</div>' if page_links else ""
    cards_html = "".join(f'<div class="card">{c}</div>' for c in cards)
    return f"<html data-csrf='{CSRF}'>{cards_html}<div class='pagination'>{page_links}</div></html>"


def schedule_card(name, code, sched_code, mode, sks, day, time_, room, lecturers, schedule_id):
    lis_schedule = (
        f'<li><div><span><i></i>{day} {time_} WIB</span>'
        f'<span><i></i>{room}</span></div></li>'
    )
    lis_dosen = "".join(f'<li><i></i>{l}</li>' for l in lecturers)
    return f"""
<div class="card border shadow-sm rounded-1">
 <div class="card-body p-3 d-flex flex-column gap-2">
  <div class="d-flex flex-wrap justify-content-between align-items-start gap-2">
   <div>
    <h5 class="fw-semibold text-dark mb-1">{name}</h5>
    <div class="small d-flex flex-wrap gap-2 align-items-center">
     <span><i></i>{code}</span>
     <span><i></i>{sched_code}</span>
     <span class="text-uppercase"><i></i>{mode}</span>
    </div>
   </div>
   <span class="badge">{sks} SKS</span>
  </div>
  <div class="border-top pt-2 mt-2"><h6>Jadwal Kuliah Reguler</h6>
   <ul class="list-unstyled">{lis_schedule}</ul></div>
  <div class="border-top pt-2 mt-2"><h6>Dosen Pengampu</h6>
   <ul class="list-unstyled">{lis_dosen}</ul></div>
  <a href="{BASE}/jadwal_perkuliahan/detail/{schedule_id}" class="btn">Detail</a>
 </div>
</div>"""


def snapshot_attr(name, comp_id="id1", data=None):
    snap = json.dumps({"data": data or {}, "memo": {
        "id": comp_id, "name": name, "path": "p", "method": "GET",
        "children": [], "scripts": [], "assets": [], "errors": [], "locale": "id"}})
    return html.escape(snap, quote=True)


def jadwal_page():
    """Schedule page carrying the two components the client expects."""
    toggle = json.dumps({"data": {}, "memo": {"id": "t1", "name": "jadwal.toggle-jadwal",
                                              "path": "", "method": "GET", "children": []}})
    main = json.dumps({"data": {}, "memo": {"id": "m1", "name": "mahasiswa.jadwal-mahasiswa",
                                            "path": "", "method": "GET", "children": []}})
    # single-quote variant on purpose: exercises the alternate delimiter path
    return (f"<html data-csrf=\"{CSRF}\">"
            f"<div wire:snapshot='{toggle}' wire:id='t'></div>"
            f"<div wire:snapshot='{main}' wire:id='m'></div>"
            "<button>list view</button></html>")


def lw_response(rendered: dict):
    """Build a livewire/update JSON response echoing rendered html per component."""
    comps = []
    for name, body in rendered.items():
        snap = json.dumps({"data": {}, "memo": {"id": "x", "name": name,
                                                "path": "", "method": "GET", "children": []}})
        comps.append({"snapshot": snap, "effects": {"html": body}})
    return json.dumps({"components": comps, "assets": []})


def mount_params(fields: dict) -> str:
    payload = {"data": {"forMount": [[fields], {"s": "arr"}]},
               "memo": {"id": "mp", "name": "__mountParamsContainer"}, "checksum": "c"}
    raw = json.dumps(payload)
    return base64.b64encode(raw.encode()).decode()


def detail_component(name, lazy_b64=None, comp_id="c1"):
    marker = ""
    if lazy_b64:
        marker = f"<span x-intersect=\"$wire.__lazyLoad(&#039;{lazy_b64}&#039;)\"></span>"
    esc = snapshot_attr(name, comp_id)
    return f'<div wire:snapshot="{esc}" wire:id="{comp_id}">{marker}</div>'


def detail_header_html(kelas="A24", dosen="Dosen Dummy, S.T., M.T.I"):
    return (
        '<div><h5 class="mt-0">Kode Jadwal</h5><p>2600000001</p></div>'
        '<div><h5 class="mt-0">Mata Kuliah</h5><p>Mata Kuliah Satu</p></div>'
        f'<div><h5 class="mt-0">Kelas</h5>{kelas}<br></div>'
        f'<div><h5 class="mt-0">Dosen</h5>{dosen}<br></div>'
        '<div><h5 class="mt-0">Ruang dan Waktu</h5><p>Ruang Kuliah Contoh 101, Senin 09:10 - 10:50</p></div>'
    )


PESERTA_TABLE_HTML = """
<div><table><thead><tr>
<th>No</th><th>Nama</th><th>Wali Setuju</th><th>Jumlah Pertemuan</th><th>Hadir</th><th>Tidak Hadir</th>
</tr></thead><tbody>
<tr><td>1</td><td>STUDENT ONE 1111110001</td><td>Ya</td><td>0</td><td>0</td><td>0</td></tr>
<tr><td>2</td><td>STUDENT TWO 2222220002</td><td>Ya</td><td>0</td><td>0</td><td>0</td></tr>
</tbody></table></div>"""


def grades_table_html(published=True):
    nilai = lambda score, letter: (f"<td>{score}</td><td>{letter}</td>" if published
                                   else "<td></td><td></td>")
    rows = "".join(
        f"<tr><td class='text-center'>{i}</td><td>2600000001</td>"
        f"<td>{name} ({code}) {sks} SKS</td><td>1. {lect}</td>{nilai(score, letter)}</tr>"
        for i, (name, code, sks, lect, score, letter) in enumerate([
            ("Mata Kuliah Satu", "INF600001", 2, "1. Dosen Satu", "85.0", "B+"),
            ("Mata Kuliah Dua", "INF600002", 3, "1. Dosen Contoh", "95", "A"),
        ], start=1)
    )
    ip_html = "3.50" if published else ""
    ipk_html = "3.40" if published else ""
    summary = (f'<tr><td colspan="7"><p>IP :<span>{ip_html}</span></p></td></tr>'
               f'<tr><td colspan="7"><p>IPK :<span>{ipk_html}</span></p></td></tr>')
    return (f"<table><thead><tr><th>No.</th><th>Kode Jadwal</th><th>Mata Kuliah</th>"
            f"<th>Dosen</th><th>Nilai</th><th>Mutu</th></tr></thead>"
            f"<tbody>{rows}{summary}</tbody></table>")


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def fake_factory(monkeypatch):
    """Factory producing (client, fake_session, fetcher) triples with the HTTP layer replaced."""
    from siakang.client import FetcherSession as _unused  # noqa: F401 - patch target module
    import siakang.client as cli

    created = {}

    def factory(handlers):
        inner = FakeSession(handlers)
        fetcher = FakeFetcherSession(inner)
        monkeypatch.setattr(cli, "FetcherSession", lambda: fetcher)
        return inner

    created["factory"] = factory
    return factory


def standard_login_handlers(dashboard_url_check=None):
    """Default happy-path login handlers."""
    return [
        ("GET", lambda u: u.endswith("/auth/login"), lambda u, k: FakeResponse(login_html(), url=u)),
        ("POST", lambda u: u.endswith("/auth/login"), lambda u, k: FakeResponse("", status=302)),
        ("GET", lambda u: "dashboard-akademik" in u,
         lambda u, k: FakeResponse(dashboard_html(), url=u)),
    ]
