"""Unit tests: HTML/JSON parsing helpers."""

import json

from siakang.client import (
    SiakangClient,
    _clean,
    _parse_jurnal,
    _parse_jurnal_meta,
    _parse_rps_sections,
    _parse_tables,
    _split_peserta_nim,
    _strip_tags,
    _to_float,
)

CARD_HTML = """
<div class="card border shadow-sm rounded-1">
 <div class="card-body p-3 d-flex flex-column gap-2">
  <div class="d-flex flex-wrap justify-content-between align-items-start gap-2">
   <div>
    <h5>Mata Kuliah Satu</h5>
    <div class="small d-flex flex-wrap gap-2 align-items-center">
     <span><i></i>INF600001</span>
     <span><i></i>2600000001</span>
     <span class="text-uppercase"><i></i>Offline</span>
    </div>
   </div>
   <span class="badge">2 SKS</span>
  </div>
  <div><h6>Jadwal Kuliah Reguler</h6>
   <ul class="list-unstyled">
    <li><div>
      <span>Senin 07:30 - 09:10 WIB</span>
      <span>Ruang Kuliah Contoh 101</span>
    </div></li>
    <li><div>
      <span>Rabu 13:00 - 14:40 WIB</span>
      <span>Ruang Lab Contoh</span>
    </div></li></ul></div>
  <div><h6>Dosen Pengampu</h6>
   <ul class="list-unstyled">
    <li>Dosen Contoh</li><li>Dosen Dummy</li></ul></div>
  <a href="https://siakang.untirta.ac.id/jadwal_perkuliahan/detail/abc123">Detail</a>
 </div>
</div>"""


class TestParseCards:
    def test_full_card(self):
        from scrapling.parser import Selector
        (c,) = SiakangClient._parse_cards(Selector(CARD_HTML))
        assert c["name"] == "Mata Kuliah Satu"
        assert c["code"] == "INF600001"
        assert c["schedule_code"] == "2600000001"
        assert c["mode"] == "Offline"
        assert c["credits"] == 2
        assert c["lecturers"] == ["Dosen Contoh", "Dosen Dummy"]
        assert c["schedule_id"] == "abc123"

    def test_multi_session_schedule(self):
        from scrapling.parser import Selector
        (c,) = SiakangClient._parse_cards(Selector(CARD_HTML))
        assert c["schedules"] == [
            {"day": "Senin", "time": "07:30 - 09:10", "room": "Ruang Kuliah Contoh 101"},
            {"day": "Rabu", "time": "13:00 - 14:40", "room": "Ruang Lab Contoh"},
        ]

    def test_missing_badge_gives_none_credits(self):
        from scrapling.parser import Selector
        html = CARD_HTML.replace('<span class="badge">2 SKS</span>', "")
        (c,) = SiakangClient._parse_cards(Selector(html))
        assert c["credits"] is None

    def test_missing_detail_link_gives_empty_id(self):
        from scrapling.parser import Selector
        html = CARD_HTML.replace("/jadwal_perkuliahan/detail/abc123", "#")
        (c,) = SiakangClient._parse_cards(Selector(html))
        assert c["schedule_id"] == ""

    def test_card_without_h5_skipped(self):
        from scrapling.parser import Selector
        html = "<div class='card'><div class='card-body'>no title</div></div>"
        assert SiakangClient._parse_cards(Selector(html)) == []

    def test_multiple_cards(self):
        from scrapling.parser import Selector
        html = f"<div>{CARD_HTML}{CARD_HTML.replace('Mata Kuliah Satu', 'Other')}</div>"
        cards = SiakangClient._parse_cards(Selector(html))
        assert len(cards) == 2


class TestHelpers:
    def test_clean_element_and_string(self):
        from scrapling.parser import Selector
        el = Selector("<p>  a\n\n b  </p>").css("p")[0]
        assert _clean(el) == "a b"
        assert _clean(" x\ty ") == "x y"

    def test_strip_tags(self):
        assert _strip_tags("<p>a<br>b</p>") == "a b"

    def test_to_float(self):
        assert _to_float("88.5") == 88.5
        assert _to_float("") is None
        assert _to_float("N/A") is None
        assert _to_float(None) is None

    def test_parse_tables_headers_rows_and_skip_empty_rows(self):
        table = ("<table><thead><tr><th>A</th><th>B</th></tr></thead>"
                 "<tbody><tr><td>1</td><td>2</td></tr>"
                 "<tr><td></td><td></td></tr></tbody></table>")
        tables = _parse_tables(table)
        assert tables == [[{"a": "1", "b": "2"}]]

    def test_parse_tables_multiple_and_empty(self):
        html = "<table></table><table><tbody><tr><td>x</td></tr></tbody></table><p>hi</p>"
        tables = _parse_tables(html)
        assert len(tables) == 1
        assert tables[0] == [{"value": "x"}]

    def test_parse_rps_sections_keeps_heading_order_and_empty(self):
        html = (
            '<h4 class="header-title">Bahan Ajar</h4>'
            '<a href="/f/1" class="fw-bold">Konsep Resiko</a>'
            '<a href="/f/1/download"><i class="dripicons-download"></i></a>'
            '<h4 class="header-title">RPS Materi</h4>'
            '<table><thead><tr><th>No</th></tr></thead><tbody></tbody></table>'
            '<h4 class="header-title">Evaluasi Aspek</h4>'
            '<table><thead><tr><th>Aspek Evaluasi</th></tr></thead><tbody>'
            '<tr><td>Ujian Akhir Semester</td></tr></tbody></table>'
        )
        out = _parse_rps_sections(html)
        assert list(out) == ["bahan_ajar", "rps_materi", "evaluasi_aspek"]
        assert out["bahan_ajar"] == [{"judul": "Konsep Resiko", "url": "/f/1"}]
        assert out["rps_materi"] == []
        assert out["evaluasi_aspek"] == [{"aspek_evaluasi": "Ujian Akhir Semester"}]

    def test_split_peserta_nim(self):
        tables = [[{"no": "1", "nama": "MAHASISWA CONTOH 3337000001"},
                   {"no": "2", "nama": "Budi"}]]
        out = _split_peserta_nim(tables)
        assert list(out[0][0]) == ["no", "nama", "nim"]
        assert out[0][0] == {"no": "1", "nama": "MAHASISWA CONTOH", "nim": "3337000001"}
        assert out[0][1] == {"no": "2", "nama": "Budi", "nim": ""}

    def test_parse_jurnal_checked_radio_and_keterangan(self):
        def radio(v, label, checked=False):
            chk = " checked" if checked else ""
            return (f'<td><div class="form-check"><input class="form-check-input" type="radio" '
                    f'value="{v}" id="{label}-s1"{chk} disabled>'
                    f'<label for="{label}-s1">{label}</label></div></td>')
        html = (
            "<table><thead><tr><th>No</th><th>Nama</th><th>Status Registrasi</th>"
            '<th colspan="4">Status Kehadiran</th><th colspan="4">Keterangan</th></tr></thead><tbody>'
            "<tr><td>1</td><td><h5>MAHASISWA CONTOH</h5><small>"
            '<span class="badge">3337000001</span></small></td>'
            '<td><span class="badge">Aktif</span></td>'
            + radio("H", "hadir") + radio("I", "izin") + radio("S", "sakit")
            + radio("A", "Tanpa Alasan", True)
            + '<td><p class="text-muted mb-0">-</p></td></tr>'
            "</tbody></table>"
        )
        out = _parse_jurnal(html)
        assert out == [{
            "no": "1",
            "nama": "MAHASISWA CONTOH",
            "nim": "3337000001",
            "status_registrasi": "Aktif",
            "status_kehadiran": "Tanpa Alasan",
            "keterangan": "-",
        }]

    def test_parse_jurnal_meta_picker_topic_and_rps_materi(self):
        html = (
            '<select class="form-select" wire:model.live="kuliah_id">'
            '<option value="" selected>-- Pilih Pertemuan</option>'
            '<option value="m1">Senin, PK. 09:10 - 10:50 || Ruang A</option>'
            '</select>'
            '<textarea class="form-control" wire:model="topik">Topik pertama</textarea>'
            '<select class="form-select" wire:model="rps_materi_id">'
            '<option value="">Pilih Salah Satu</option>'
            '<option value="r1" selected>Konsep Resiko I</option>'
            '</select>'
        )
        meta = _parse_jurnal_meta(html)
        assert meta == {
            "pertemuan": [{"id": "", "label": "-- Pilih Pertemuan"},
                          {"id": "m1", "label": "Senin, PK. 09:10 - 10:50 || Ruang A"}],
            "kuliah_id": "",
            "topik": "Topik pertama",
            "rps_materi": "Konsep Resiko I",
        }

    def test_split_peserta_nim_reorders_when_nim_is_separate_column(self):
        """nim right after nama even when the site already provides a nim column."""
        tables = [[{"no": "1", "nama": "MAHASISWA CONTOH",
                    "wali_setuju": "Ya", "nim": "3337000001"}]]
        out = _split_peserta_nim(tables)
        assert list(out[0][0]) == ["no", "nama", "nim", "wali_setuju"]
