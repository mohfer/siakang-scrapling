"""Additional client scenarios: challenge retry and detail-enriched schedules."""

import base64
import html
import json
import os

import pytest
from dotenv import load_dotenv

from siakang.client import BASE, SiakangClient, SiakangUpstreamError

from conftest import (
    CSRF,
    FakeFetcherSession,
    FakeResponse,
    FakeSession,
    PESERTA_TABLE_HTML,
    dashboard_html,
    jadwal_page,
    list_semesters_page,
    lw_response,
    schedule_card,
    semester_card,
)

SCHEDULE_ID = "10000000-0000-0000-0000-000000000001"
CHALLENGE_HTML = ('<html><body>'
                  '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js">'
                  '</script></body></html>')


def _mount_b64(fields):
    payload = {"data": {"forMount": [[fields], {"s": "arr"}]},
               "memo": {"name": "__mountParamsContainer"}}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def header_html(kelas):
    return (
        '<div><h5 class="mt-0">Kode Jadwal</h5><p>2600000001</p></div>'
        '<div><h5 class="mt-0">Mata Kuliah</h5><p>Mata Kuliah Satu</p></div>'
        f'<div><h5 class="mt-0">Kelas</h5>{kelas}<br></div>'
        '<div><h5 class="mt-0">Dosen</h5>Dosen Dummy<br></div>'
    )


def detail_page_html(kelas="A24"):
    def component(name, b64=None):
        marker = ""
        if b64:
            marker = f"<span x-intersect=\"$wire.__lazyLoad(&#039;{b64}&#039;)\"></span>"
        snap = html.escape(json.dumps({"data": {}, "memo": {
            "id": "c", "name": name, "path": "", "method": "GET", "children": []}}), quote=True)
        return f'<div wire:snapshot="{snap}">{marker}</div>'

    return (
        f"<html data-csrf=\"{CSRF}\">"
        + component("pengajaran.detail-kuliah", _mount_b64({"isJadwalBlok": False}))
        + component("pengajaran.manajemen-kuliah")
        + component("jadwal.peserta", _mount_b64({"canExportPeserta": False}))
        + "</html>"
    )


class TestGetPageRetry:
    def _open(self, monkeypatch):
        handlers = [
            ("GET", lambda u: u.endswith("/auth/login"),
             lambda u, k: FakeResponse(
                 f'<html data-csrf="{CSRF}">'
                 '<input type="hidden" name="_token" value="t"></html>', url=u)),
            ("POST", lambda u: u.endswith("/auth/login"),
             lambda u, k: FakeResponse("", status=302)),
            ("GET", lambda u: "dashboard-akademik" in u,
             lambda u, k: FakeResponse(dashboard_html(),
                                       url=f"{BASE}/dashboard/dashboard-akademik")),
        ]
        inner = FakeSession(handlers)
        monkeypatch.setattr("siakang.client.FetcherSession",
                            lambda: FakeFetcherSession(inner))
        return SiakangClient(email="a", password="b").__enter__()

    def test_challenge_page_retried_once_then_recovers(self, monkeypatch):
        c = self._open(monkeypatch)
        responses = [FakeResponse(CHALLENGE_HTML),
                     FakeResponse(f'<html data-csrf="{CSRF}">real content</html>')]
        state = {"i": 0}

        def fake_get(url, headers=None, **k):
            r = responses[state["i"]]
            state["i"] += 1
            return r
        monkeypatch.setattr(c._session, "get", fake_get)
        raw = c._get_page(f"{BASE}/jadwal_perkuliahan", f"{BASE}/")
        assert "real content" in raw

    def test_persistent_challenge_raises_upstream_error(self, monkeypatch):
        c = self._open(monkeypatch)
        monkeypatch.setattr(c._session, "get",
                            lambda url, headers=None, **k: FakeResponse(CHALLENGE_HTML))
        with pytest.raises(SiakangUpstreamError, match="Repeated challenge"):
            c._get_page(f"{BASE}/jadwal_perkuliahan", f"{BASE}/")

    def test_redirect_to_login_raises_upstream_error(self, monkeypatch):
        c = self._open(monkeypatch)
        monkeypatch.setattr(c._session, "get",
                            lambda url, headers=None, **k: FakeResponse(
                                "<html>expired session</html>",
                                url=f"{BASE}/auth/login"))
        with pytest.raises(SiakangUpstreamError, match="Repeated challenge"):
            c._get_page(f"{BASE}/jadwal_perkuliahan", f"{BASE}/")


class TestScheduleWithDetail:
    def test_detail_true_enriches_every_row(self, monkeypatch):
        """detail=True attaches per-course get_detail output to every row."""
        kelas_by_id = {SCHEDULE_ID: "A24", "id-cloud": "B24"}
        cards = "".join([
            schedule_card("Mata Kuliah Satu", "INF600001", "2600000001", "Offline", 2,
                          "Senin", "09:10 - 10:50", "Ruang Kuliah Contoh 101", ["Dosen Dummy"],
                          SCHEDULE_ID),
            schedule_card("Mata Kuliah Dua", "INF600002", "2600000002", "Offline", 3,
                          "Rabu", "13:00 - 15:30", "Ruang Lab", ["Dosen Lain"], "id-cloud"),
        ])
        pages = {
            f"{BASE}/dashboard/list-semester": FakeResponse(
                list_semesters_page([semester_card("20261", "2026/2027 Gasal", "u-261", active=True)])),
            f"{BASE}/dashboard/change-semester/u-261": FakeResponse(dashboard_html()),
            f"{BASE}/jadwal_perkuliahan": FakeResponse(jadwal_page()),
        }
        for sid, kelas in kelas_by_id.items():
            pages[f"{BASE}/jadwal_perkuliahan/detail/{sid}"] = FakeResponse(
                detail_page_html(kelas))

        def livewire(u, kw):
            headers = kw.get("headers") or {}
            body = kw["json"]
            updates = None
            comp = body["components"][0]
            snap = json.loads(comp["snapshot"])
            name = snap["memo"]["name"]
            calls = comp.get("calls", [])
            updates = comp.get("updates", {}) or {}
            if calls and calls[0]["method"] == "__lazyLoad":
                if name == "jadwal.peserta":
                    body_html = PESERTA_TABLE_HTML
                else:
                    ref = str(headers.get("referer", ""))
                    sid = ref.rsplit("/", 1)[-1]
                    body_html = header_html(kelas_by_id.get(sid, ""))
                return FakeResponse(lw_response({name: body_html}), content_type="json")
            if "active_menu" in updates:
                return FakeResponse(lw_response({
                    "pengajaran.manajemen-kuliah": "<div>menus</div>"}), content_type="json")
            return FakeResponse(lw_response({
                "jadwal.toggle-jadwal": "",
                "mahasiswa.jadwal-mahasiswa": cards,
            }), content_type="json")

        handlers = [
            ("GET", lambda u: u.endswith("/auth/login"),
             lambda u, k: FakeResponse(
                 f'<html data-csrf="{CSRF}">'
                 '<input type="hidden" name="_token" value="t"></html>', url=u)),
            ("POST", lambda u: u.endswith("/auth/login"),
             lambda u, k: FakeResponse("", status=302)),
            ("GET", lambda u: "dashboard-akademik" in u,
             lambda u, k: FakeResponse(dashboard_html(),
                                       url=f"{BASE}/dashboard/dashboard-akademik")),
            ("GET", lambda u: True, lambda u, k: pages[u]),
            ("POST", lambda u: True, livewire),
        ]
        inner = FakeSession(handlers)
        monkeypatch.setattr("siakang.client.FetcherSession",
                            lambda: FakeFetcherSession(inner))

        load_dotenv(".env")
        client = SiakangClient(email=os.getenv("EMAIL"),
                               password=os.getenv("PASSWORD")).__enter__()
        rows = client.get_schedule(detail=True)

        assert len(rows) == 2
        for r in rows:
            assert r["detail"]["header"]["Kelas"] == kelas_by_id[r["schedule_id"]]
            peserta_rows = sum(len(t["rows"])
                               for t in r["detail"]["tabs"]["peserta"]["tables"])
            assert peserta_rows >= 1

    def test_lazy_component_failure_does_not_crash(self, monkeypatch):
        """A failing lazy component is skipped; the rest still renders."""
        pages = {
            f"{BASE}/jadwal_perkuliahan/detail/{SCHEDULE_ID}": FakeResponse(
                detail_page_html("A24")),
            f"{BASE}/livewire/update": FakeResponse("err", status=500, content_type="json"),
        }
        handlers = [
            ("GET", lambda u: u.endswith("/auth/login"),
             lambda u, k: FakeResponse(
                 f'<html data-csrf="{CSRF}">'
                 '<input type="hidden" name="_token" value="t"></html>', url=u)),
            ("POST", lambda u: u.endswith("/auth/login"),
             lambda u, k: FakeResponse("", status=302)),
            ("GET", lambda u: "dashboard-akademik" in u,
             lambda u, k: FakeResponse(dashboard_html(), url=u)),
            ("GET", lambda u: True, lambda u, k: pages[u]),
            ("POST", lambda u: True,
             lambda u, k: FakeResponse("err", status=500, content_type="json")),
        ]
        inner = FakeSession(handlers)
        monkeypatch.setattr("siakang.client.FetcherSession",
                            lambda: FakeFetcherSession(inner))

        load_dotenv(".env")
        client = SiakangClient(email=os.getenv("EMAIL"),
                               password=os.getenv("PASSWORD")).__enter__()
        d = client.get_detail(SCHEDULE_ID)
        # every tab reports the upstream error instead of raising
        assert all(entry["error"] for entry in d["tabs"].values())
