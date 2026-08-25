"""Cache backends for class-letter lookups. Custom backends only need get/set."""

import json
from pathlib import Path


class NullCache:
    """No caching — always fetch fresh data."""

    def get(self, key):
        return None

    def set(self, key, value):
        pass


class FileCache:
    """Simple JSON file cache. Fine for development / single-instance apps."""

    def __init__(self, path: str | Path = ".siakang_class_cache.json"):
        self.path = Path(path)
        try:
            self._data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value
        self.path.write_text(json.dumps(self._data, ensure_ascii=False))
