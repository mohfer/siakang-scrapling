"""Unit tests: HTML/JSON parsing helpers."""

import json

from siakang.client import (
    SiakangClient,
    _clean,
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
        assert tables == [{"headers": ["A", "B"], "rows": [["1", "2"]]}]

    def test_parse_tables_multiple_and_empty(self):
        html = "<table></table><table><tbody><tr><td>x</td></tr></tbody></table><p>hi</p>"
        tables = _parse_tables(html)
        assert len(tables) == 1
        assert tables[0]["rows"] == [["x"]]

    def test_split_peserta_nim(self):
        tables = [{"headers": ["No", "Nama"], "rows": [["1", "MAHASISWA CONTOH 3337000001"], ["2", "Budi"]]}]
        out = _split_peserta_nim(tables)
        assert out[0]["headers"] == ["No", "Nama", "NIM"]
        assert out[0]["rows"][0] == ["1", "MAHASISWA CONTOH", "3337000001"]
        assert out[0]["rows"][1] == ["2", "Budi", ""]
