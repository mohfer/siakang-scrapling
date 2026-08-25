"""End-to-end client flow tests over a fully faked HTTP layer."""

import html
import json

import pytest

from siakang import SiakangClient, SiakangError
from siakang.client import BASE, SiakangAuthError, SiakangNotFoundError, SiakangUpstreamError
from siakang.cache import FileCache

from conftest import (
    CSRF,
    FakeFetcherSession,
    FakeResponse,
    FakeSession,
    dashboard_html,
    grades_table_html,
    jadwal_page,
    list_semesters_page,
    login_html,
    lw_response,
    schedule_card,
    semester_card,
)

SCHEDULE_ID = "10000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------- helpers


def schedule_cards_fragment():
    cards = [
        schedule_card("Mata Kuliah Satu", "INF600001", "2600000001", "Offline", 2,
                      "Senin", "09:10 - 10:50", "Ruang Kuliah Contoh 101", ["Dosen Dummy"], SCHEDULE_ID),
        schedule_card("Mata Kuliah Dua", "INF600002", "2600000002", "Offline", 3,
                      "Rabu", "13:00 - 15:30", "Ruang Lab", ["Dosen Lain"], "id-cloud"),
    ]
    return "".join(cards)


def detail_page_html():
    def b64(fields):
        payload = {"data": {"forMount": [[fields], {"s": "arr"}]},
                   "memo": {"id": "mp", "name": "__mountParamsContainer"}, "checksum": "c"}
        import base64
        return base64.b64encode(json.dumps(payload).encode()).decode()

    def component(name, b64=None, cid="c"):
        marker = ""
        if b64:
            marker = f"<span x-intersect=\"$wire.__lazyLoad(&#039;{b64}&#039;)\"></span>"
        snap = html.escape(json.dumps({"data": {}, "memo": {
            "id": cid, "name": name, "path": "", "method": "GET", "children": []}}), quote=True)
        return f'<div wire:snapshot="{snap}" wire:id="{cid}">{marker}</div>'

    return (
        f"<html data-csrf=\"{CSRF}\">"
        + component("pengajaran.detail-kuliah", b64({"isJadwalBlok": False}))
        + component("pengajaran.manajemen-kuliah")
        + component("jadwal.peserta", b64({"canExportPeserta": False}))
        + "</html>"
    )


HEADER_HTML = (
    '<div><h5 class="mt-0">Kode Jadwal</h5><p>2600000001</p></div>'
    '<div><h5 class="mt-0">Mata Kuliah</h5><p>Mata Kuliah Satu</p></div>'
    '<div><h5 class="mt-0">Kelas</h5>A24<br></div>'
    '<div><h5 class="mt-0">Dosen</h5>Dosen Dummy, S.T., M.T.I<br></div>'
)

PESERTA_HTML = ("<table><thead><tr><th>No</th><th>Nama</th><th>Wali Setuju</th>"
                "<th>Jumlah Pertemuan</th><th>Hadir</th><th>Tidak Hadir</th></tr></thead>"
                "<tbody><tr><td>1</td><td>STUDENT ONE</td><td>Ya</td><td>0</td>"
                "<td>0</td><td>0</td></tr></tbody></table>")

CHALLENGE_HTML = '<html><body><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></body></html>'


def make_handlers(*, login_ok=True, pages=None, livewire=None):
    """Build standard login routes plus custom page/livewire responders."""
    dash_url = (f"{BASE}/dashboard/dashboard-akademik" if login_ok
                else f"{BASE}/auth/login")
    handlers = [
        ("GET", lambda u: u.endswith("/auth/login"),
         lambda u, k: FakeResponse(login_html(), url=u)),
        ("POST", lambda u: u.endswith("/auth/login"),
         lambda u, k: FakeResponse("", status=302)),
        ("GET", lambda u: "dashboard-akademik" in u,
         lambda u, k: FakeResponse(dashboard_html(), url=dash_url)),
    ]

    def fallback_get(url, k):
        resp = pages.get(url)
        if resp is None:
            raise AssertionError(f"unrouted GET {url}")
        return resp

    handlers.append(("GET", lambda u: True, fallback_get))

    def livewire_route(u, k):
        if livewire is None:
            raise AssertionError(f"unexpected livewire POST ({k})")
        return livewire(u, k)

    handlers.append(("POST", lambda u: u.endswith("/livewire/update"), livewire_route))
    return handlers


def open_client(monkeypatch, handlers, class_letters=None):
    inner = FakeSession(handlers)
    fetcher = FakeFetcherSession(inner)
    monkeypatch.setattr("siakang.client.FetcherSession", lambda: fetcher)

    letters = dict(class_letters or {})
    if class_letters is not None:
        def fake_fetch(self, cookies, href):
            key = href.rsplit("/", 1)[-1]
            return key, letters.get(key, "")
        monkeypatch.setattr(SiakangClient, "_fetch_one_class", fake_fetch)

    client = SiakangClient(email="a@b.c", password="pw").__enter__()
    return client, inner


def livewire_mode_card_responder():
    def handler(u, k):
        return FakeResponse(lw_response({
            "jadwal.toggle-jadwal": "",
            "mahasiswa.jadwal-mahasiswa": schedule_cards_fragment(),
        }), content_type="json")
    return handler


# ---------------------------------------------------------------- tests


class TestLogin:
    def test_wrong_password_raises_auth_and_closes_session(self, monkeypatch):
        handlers = make_handlers(login_ok=False)
        inner = FakeSession(handlers)
        fetcher = FakeFetcherSession(inner)
        monkeypatch.setattr("siakang.client.FetcherSession", lambda: fetcher)
        with pytest.raises(SiakangAuthError):
            SiakangClient(email="a@b.c", password="wrong").__enter__()
        assert inner.closed is True  # session must not leak on failure

    def test_login_page_without_token_is_upstream_error(self, monkeypatch):
        handlers = [
            ("GET", lambda u: u.endswith("/auth/login"),
             lambda u, k: FakeResponse("<html><body>no form</body></html>", url=u)),
        ]
        inner = FakeSession(handlers)
        monkeypatch.setattr("siakang.client.FetcherSession", lambda: FakeFetcherSession(inner))
        with pytest.raises(SiakangUpstreamError):
            SiakangClient(email="a@b.c", password="p").__enter__()
        assert inner.closed is True


class TestSessionPersistence:
    def _client(self, monkeypatch, handlers, **kw):
        inner = FakeSession(handlers)
        monkeypatch.setattr("siakang.client.FetcherSession", lambda: FakeFetcherSession(inner))
        return SiakangClient(email="a@b.c", password="pw", **kw).__enter__(), inner

    def test_saves_cookies_after_login(self, monkeypatch, tmp_path):
        path = tmp_path / "sess.json"
        self._client(monkeypatch, make_handlers(), session_file=path)
        saved = json.loads(path.read_text())
        assert "siakang_session" in saved

    def test_valid_saved_session_skips_login(self, monkeypatch, tmp_path):
        # no /auth/login routes registered: entering must not touch them
        handlers = [("GET", lambda u: "dashboard-akademik" in u,
                     lambda u, k: FakeResponse(dashboard_html(),
                                               url=f"{BASE}/dashboard/dashboard-akademik"))]
        path = tmp_path / "sess.json"
        path.write_text(json.dumps({"siakang_session": "saved"}))
        client, inner = self._client(monkeypatch, handlers, session_file=path)
        assert client._csrf == CSRF
        assert all("/auth/login" not in u for _, u in inner.calls)

    def test_expired_session_falls_back_to_full_login(self, monkeypatch, tmp_path):
        state = {"logged_in": False}

        def dash(u, k):  # expired cookie -> server bounces to the login page
            if not state["logged_in"]:
                return FakeResponse(login_html(), url=f"{BASE}/auth/login")
            return FakeResponse(dashboard_html(), url=f"{BASE}/dashboard/dashboard-akademik")

        def login_post(u, k):
            state["logged_in"] = True
            return FakeResponse("", status=302)

        handlers = [
            ("GET", lambda u: "dashboard-akademik" in u, dash),
            ("GET", lambda u: u.endswith("/auth/login"),
             lambda u, k: FakeResponse(login_html(), url=u)),
            ("POST", lambda u: u.endswith("/auth/login"), login_post),
        ]
        path = tmp_path / "sess.json"
        path.write_text(json.dumps({"siakang_session": "stale"}))
        client, inner = self._client(monkeypatch, handlers, session_file=path)
        assert any(m == "POST" and u.endswith("/auth/login") for m, u in inner.calls)

    def test_default_paths_differ_per_account(self, tmp_path):
        a = SiakangClient(email="a@b.c", password="p", session_file=True)._session_cookie_path()
        b = SiakangClient(email="other@b.c", password="p", session_file=True)._session_cookie_path()
        assert a != b


class TestGuards:
    def test_methods_without_with_raise_clear_error(self):
        c = SiakangClient(email="a@b.c", password="p")
        with pytest.raises(SiakangError, match="not open"):
            c.list_semesters()
        with pytest.raises(SiakangError, match="not open"):
            c.get_schedule()
        with pytest.raises(SiakangError, match="not open"):
            c.get_grades()

    def test_exit_without_enter_is_safe(self):
        SiakangClient(email="a", password="b").__exit__(None, None, None)


class TestListSemesters:
    def test_pagination_and_parsing(self, monkeypatch):
        p1 = list_semesters_page(
            [semester_card("20261", "2026/2027 Gasal", "uuid-261", active=True),
             semester_card("20252", "2025/2026 Genap", "uuid-252")],
            next_page=2)
        p2 = list_semesters_page([semester_card("20251", "2025/2026 Gasal", "uuid-251")])
        pages = {f"{BASE}/dashboard/list-semester": FakeResponse(p1),
                 f"{BASE}/dashboard/list-semester?page=2": FakeResponse(p2)}
        client, _ = open_client(monkeypatch, make_handlers(pages=pages))
        semesters = client.list_semesters()
        assert [(s["code"], s["active"]) for s in semesters] == [("20261", True), ("20252", False), ("20251", False)]
        assert all(set(s) == {"code", "name", "id", "active"} for s in semesters)


class TestGetSchedule:
    def _handlers(self, *, jadwal_html=None, lw_status=200, livewire_override=None):
        pages = {
            f"{BASE}/dashboard/list-semester": FakeResponse(
                list_semesters_page([semester_card("20261", "2026/2027 Gasal", "u-261", active=True)])),
            f"{BASE}/dashboard/change-semester/u-261": FakeResponse(dashboard_html()),
            f"{BASE}/jadwal_perkuliahan": FakeResponse(jadwal_html or jadwal_page()),
        }

        def livewire(u, k):
            body = k["json"]
            if lw_status != 200:
                return FakeResponse("error", status=lw_status, content_type="json")
            names = {json.loads(c["snapshot"])["memo"]["name"] for c in body["components"]}
            if {"jadwal.toggle-jadwal", "mahasiswa.jadwal-mahasiswa"} <= names:
                return FakeResponse(lw_response({
                    "jadwal.toggle-jadwal": "",
                    "mahasiswa.jadwal-mahasiswa": schedule_cards_fragment(),
                }), content_type="json")
            return FakeResponse("{}", status=lw_status, content_type="json")

        return make_handlers(pages=pages, livewire=livewire_override or livewire)

    def test_happy_path_parses_cards_and_classes(self, monkeypatch):
        letters = {SCHEDULE_ID: "A24", "id-cloud": "B24"}
        client, _ = open_client(monkeypatch, self._handlers(), class_letters=letters)
        rows = client.get_schedule(semester="20261")

        assert [r["name"] for r in rows] == ["Mata Kuliah Satu", "Mata Kuliah Dua"]
        assert rows[0]["class"] == "A24"
        assert rows[1]["credits"] == 3
        assert rows[0]["lecturers"] == ["Dosen Dummy"]

    def test_unknown_semester_raises_not_found(self, monkeypatch):
        p1 = list_semesters_page([semester_card("20261", "2026/2027 Gasal", "u1")])
        pages = {f"{BASE}/dashboard/list-semester": FakeResponse(p1)}
        client, _ = open_client(monkeypatch, make_handlers(pages=pages))
        with pytest.raises(SiakangNotFoundError, match="99999"):
            client.get_schedule(semester="99999")

    def test_livewire_500_is_upstream_error(self, monkeypatch):
        client, _ = open_client(monkeypatch, self._handlers(lw_status=500))
        with pytest.raises(SiakangUpstreamError):
            client.get_schedule()

    def test_renamed_components_raise_upstream_error(self, monkeypatch):
        client, _ = open_client(monkeypatch, self._handlers(jadwal_html="<html data-csrf='x'>no comps</html>"))
        with pytest.raises(SiakangUpstreamError, match="Livewire components changed"):
            client.get_schedule()

    def test_empty_cards_fragment_raises_upstream_error(self, monkeypatch):
        def livewire(u, k):
            return FakeResponse(lw_response({"jadwal.toggle-jadwal": "",
                                             "mahasiswa.jadwal-mahasiswa": "<div>no cards</div>"}),
                                content_type="json")
        client, _ = open_client(monkeypatch, self._handlers(livewire_override=livewire))
        with pytest.raises(SiakangUpstreamError, match="list view switch failed"):
            client.get_schedule()


class TestGetGrades:
    def _handlers(self, published=True):
        pages = {
            f"{BASE}/dashboard/list-semester": FakeResponse(
                list_semesters_page([semester_card("20251", "2025/2026 Gasal", "uuid-251")])),
            f"{BASE}/dashboard/change-semester/uuid-251": FakeResponse(dashboard_html()),
            f"{BASE}/hasil-studi": FakeResponse(grades_table_html(published=published)),
        }
        return make_handlers(pages=pages)

    def test_published_grades(self, monkeypatch):
        client, _ = open_client(monkeypatch, self._handlers())
        res = client.get_grades(semester="20251")
        assert res["ip"] == 3.50 and res["ipk"] == 3.40
        first = res["courses"][0]
        assert first["code"] == "INF600001"
        assert first["name"] == "Mata Kuliah Satu"
        assert first["score"] == 85.0
        assert first["letter"] == "B+"
        assert first["lecturers"] == ["Dosen Satu"]

    def test_unpublished_grades_are_none(self, monkeypatch):
        client, _ = open_client(monkeypatch, self._handlers(published=False))
        res = client.get_grades()
        assert res["ip"] is None and res["ipk"] is None
        assert all(c["score"] is None and c["letter"] is None for c in res["courses"])

    def test_non_numeric_score_does_not_crash(self, monkeypatch):
        html = grades_table_html().replace("<td>85.0</td>", "<td>T</td>")
        pages = {f"{BASE}/hasil-studi": FakeResponse(html)}
        client, _ = open_client(monkeypatch, make_handlers(pages=pages))
        res = client.get_grades()
        scores = {c["score"] for c in res["courses"]}
        assert None in scores


class TestGetDetail:
    def _handlers(self):
        def livewire(u, k):
            body = k["json"]
            comp = body["components"][0]
            snap = json.loads(comp["snapshot"])
            name = snap["memo"]["name"]
            calls = comp.get("calls", [])
            if calls and calls[0]["method"] == "__lazyLoad":
                if name == "jadwal.peserta":
                    return FakeResponse(lw_response({name: PESERTA_HTML}), content_type="json")
                if name == "pengajaran.detail-kuliah":
                    return FakeResponse(lw_response({name: HEADER_HTML}), content_type="json")
                return FakeResponse("err", status=500, content_type="json")
            updates = comp.get("updates", {})
            tab = updates.get("active_menu")
            if tab == "rps_bahan_ajar":
                child = json.dumps({"data": {}, "memo": {
                    "id": "ch", "name": "pengajaran.rps-bahan-ajar-extra",
                    "path": "", "method": "GET", "children": []}})
                import base64
                b64 = base64.b64encode(json.dumps(
                    {"data": {"forMount": [[{}], {"s": "arr"}]},
                     "memo": {"name": "__mountParamsContainer"}}).encode()).decode()
                menu = ('<div>menus</div>'
                        f'<div wire:snapshot="{html.escape(child, quote=True)}" wire:id="ch">'
                        f'<span x-intersect="$wire.__lazyLoad(&#039;{b64}&#039;)"></span></div>')
                return FakeResponse(lw_response({"pengajaran.manajemen-kuliah": menu}),
                                    content_type="json")
            return FakeResponse(lw_response({"pengajaran.manajemen-kuliah": f"<div>{tab}</div>"}),
                                content_type="json")

        pages = {f"{BASE}/jadwal_perkuliahan/detail/{SCHEDULE_ID}": FakeResponse(detail_page_html())}
        return make_handlers(pages=pages, livewire=livewire)

    def test_header_tabs_and_peserta_rows(self, monkeypatch):
        client, _ = open_client(monkeypatch, self._handlers())
        d = client.get_detail(SCHEDULE_ID)

        assert d["header"]["Kelas"] == "A24"
        assert d["header"]["Dosen"] == "Dosen Dummy, S.T., M.T.I"
        assert set(d["tabs"]) == {"rps_bahan_ajar", "peserta",
                                  "jurnal_perkuliahan", "rekap_jurnal_perkuliahan"}
        rows = d["tabs"]["peserta"]["tables"][0]["rows"]
        assert rows[0][1] == "STUDENT ONE"

    def test_tab_error_is_reported_not_raised(self, monkeypatch):
        client, _ = open_client(monkeypatch, self._handlers())
        d = client.get_detail(SCHEDULE_ID)
        # tabs without dedicated lazy handler fall back gracefully (no crash)
        assert all("error" in entry for entry in d["tabs"].values())
