"""Unit tests: wire snapshot extraction, lazy markers, and lazy hydration."""

import html
import json

import pytest

from siakang.client import SiakangClient


def b64_for(fields):
    payload = {"data": {"forMount": [[fields], {"s": "arr"}]},
               "memo": {"id": "mp", "name": "__mountParamsContainer"}, "checksum": "c"}
    import base64
    return base64.b64encode(json.dumps(payload).encode()).decode()


class TestWireSnapshots:
    def test_double_quoted_attribute(self):
        raw = '<div wire:snapshot="{&quot;a&quot;:1}" wire:id="x"></div>'
        assert SiakangClient._wire_snapshots(raw) == ['{"a":1}']

    def test_single_quoted_attribute(self):
        raw = """<div wire:snapshot='{"a":1}' wire:id="x"></div>"""
        assert SiakangClient._wire_snapshots(raw) == ['{"a":1}']

    def test_snapshot_as_last_attribute(self):
        raw = "<div wire:snapshot='{&quot;a&quot;:1}'>"
        assert len(SiakangClient._wire_snapshots(raw)) == 1

    def test_multiple_components(self):
        raw = ("<div wire:snapshot='{&quot;a&quot;:1}' wire:id='1'></div>"
               "<div wire:snapshot='{&quot;b&quot;:2}' wire:id='2'></div>")
        snaps = SiakangClient._wire_snapshots(raw)
        assert [json.loads(s) for s in snaps] == [{"a": 1}, {"b": 2}]

    def test_none_present(self):
        assert SiakangClient._wire_snapshots("<p>plain</p>") == []


class TestLazyMarkers:
    def test_literal_single_quote(self):
        raw = "<span x-intersect=\"$wire.__lazyLoad('eyJhIjoxfQ==')\"></span>"
        markers = SiakangClient._lazy_load_markers(raw)
        assert list(markers.values()) == ["eyJhIjoxfQ=="]

    def test_escaped_html_quote(self):
        raw = "<span x-intersect=\"$wire.__lazyLoad(&#039;eyJhIjoxfQ==&#039;)\"></span>"
        markers = SiakangClient._lazy_load_markers(raw)
        assert list(markers.values()) == ["eyJhIjoxfQ=="]

    def test_double_quote(self):
        raw = '<span x-intersect="$wire.__lazyLoad(&quot;eyJhIjoxfQ==&quot;)"></span>'
        assert list(SiakangClient._lazy_load_markers(raw).values()) == ["eyJhIjoxfQ=="]

    def test_positions_are_document_order(self):
        raw = ("x" * 50 + "$wire.__lazyLoad('QQ==')" + "y" * 20 +
               "$wire.__lazyLoad('Qg==')")
        positions = list(SiakangClient._lazy_load_markers(raw))
        assert positions[0] < positions[1]


class TestHydrateLazy:
    def _client(self, monkeypatch, responses):
        """Client whose _wire_commit returns canned html per call index."""
        c = object.__new__(SiakangClient)
        seen = []

        def fake_commit(url, snapshot, updates=None, calls=None):
            idx = len(seen)
            seen.append(snapshot)
            return responses[min(idx, len(responses) - 1)]

        monkeypatch.setattr(c, "_wire_commit", fake_commit)
        return c, seen

    def test_single_level(self, monkeypatch):
        marker_b64 = b64_for({"canExportPeserta": False})
        snap = html.escape(json.dumps({"memo": {"name": "jadwal.peserta"}}), quote=True)
        segment = (
            f'<div wire:snapshot="{snap}">'
            f"<span x-intersect=\"$wire.__lazyLoad('{marker_b64}')\"></span></div>"
        )
        # escape quotes the way livewire would in an attribute
        c, calls = self._client(monkeypatch, ["<table>rows</table>"])
        rendered = c._hydrate_lazy("http://x", segment)
        assert rendered["jadwal.peserta"] == "<table>rows</table>"

    def test_nested_two_levels(self, monkeypatch):
        grandchild_snap = json.dumps({"memo": {"name": "rps.detail-rps"}})
        child_render = (
            "<div>RPS-HEADER</div>"
            + f'<div wire:snapshot=\'{json.dumps({"memo": {"name": "rps.detail-rps"}})}\'>'
            + f"<span x-intersect=\"$wire.__lazyLoad('{b64_for({'rpsId': 'x'})}')\"></span></div>"
        )
        responses = [child_render, "<table>RPS-TABLE</table>"]
        c, calls = self._client(monkeypatch, responses)
        marker = b64_for({"rpsId": None})
        segment = (
            "<div>wrapper</div>"
            + f'<div wire:snapshot=\'{json.dumps({"memo": {"name": "pengajaran.rps-bahan-ajar-extra"}})}\'>'
            + f"<span x-intersect=\"$wire.__lazyLoad('{marker}')\"></span></div>"
        )
        rendered = c._hydrate_lazy("http://x", segment)
        joined = "\n".join(rendered.values())
        assert "RPS-HEADER" in joined
        assert "RPS-TABLE" in joined
        assert len(calls) == 2

    def test_depth_guard(self, monkeypatch):
        c, _ = self._client(monkeypatch, ["<div>deep</div>"])
        def make(depth):
            snap = json.dumps({"memo": {"name": f"n{depth}"}})
            marker = b64_for({"n": depth})
            return ('<div wire:snapshot=\'' + snap + '\'>'
                    + "<span x-intersect=\"$wire.__lazyLoad('" + marker + "')\"></span></div>")
        seg = "".join(make(d) for d in range(10))
        rendered = c._hydrate_lazy("http://x", seg)
        assert isinstance(rendered, dict)
