"""Unit tests: cache backends and the class-letter fill logic."""

import json

import pytest

from siakang.cache import FileCache, NullCache
from siakang.client import SiakangClient


class TestNullCache:
    def test_get_returns_none_and_set_is_noop(self):
        c = NullCache()
        c.set("a", "A24")
        assert c.get("a") is None


class TestFileCache:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "cache.json"
        c = FileCache(p)
        assert c.get("x") is None
        c.set("x", "A24")
        assert FileCache(p).get("x") == "A24"  # survives a new instance

    def test_missing_file_starts_empty(self, tmp_path):
        assert FileCache(tmp_path / "nope.json").get("x") is None

    def test_corrupt_file_starts_empty(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert FileCache(p).get("x") is None


class FakeCache:
    def __init__(self, initial=None):
        self.d = dict(initial or {})

    def get(self, key):
        return self.d.get(key)

    def set(self, key, value):
        self.d[key] = value


def _courses(*schedule_ids):
    return [{"name": f"c{i}", "schedule_id": sid, "class": ""}
            for i, sid in enumerate(schedule_ids)]


class TestFillClass:
    def _client(self, monkeypatch, fetch_results):
        """Client with _fetch_one_class stubbed to pop from fetch_results."""
        from conftest import FakeSession as _FS
        c = object.__new__(SiakangClient)
        c.cache = None
        c.max_workers = 4
        c._session = _FS([])
        fetched = []

        def fake(self, cookies, href):
            key = href.rsplit("/", 1)[-1]
            fetched.append(key)
            return key, fetch_results.get(key, "")

        monkeypatch.setattr(SiakangClient, "_fetch_one_class", fake)
        c.fetched = fetched
        return c

    def test_cache_hit_skips_fetch(self, monkeypatch):
        c = self._client(monkeypatch, {})
        c.cache = FakeCache({"id1": "A24"})
        courses = _courses("id1")
        c._fill_class(courses)
        assert courses[0]["class"] == "A24"
        assert c.fetched == []

    def test_cache_miss_fetches_then_stores(self, monkeypatch):
        c = self._client(monkeypatch, {"id1": "B24"})
        c.cache = FakeCache()
        courses = _courses("id1")
        c._fill_class(courses)
        assert courses[0]["class"] == "B24"
        assert c.fetched == ["id1"]
        assert c.cache.get("id1") == "B24"

    def test_failed_fetch_not_cached(self, monkeypatch):
        c = self._client(monkeypatch, {"id1": ""})  # upstream failure -> empty
        c.cache = FakeCache()
        courses = _courses("id1")
        c._fill_class(courses)
        assert courses[0]["class"] == ""
        assert "id1" not in c.cache.d  # empty result must not poison the cache
        # next run retries and succeeds
        fetch_results = {"id1": "C24"}
        monkeypatch.setattr(SiakangClient, "_fetch_one_class",
                            lambda self, cookies, href: ("id1", "C24"))
        c._fill_class(courses)
        assert courses[0]["class"] == "C24"

    def test_no_schedule_id_never_fetched(self, monkeypatch):
        c = self._client(monkeypatch, {})
        courses = [{"name": "x", "schedule_id": "", "class": ""}]
        c._fill_class(courses)
        assert c.fetched == []
