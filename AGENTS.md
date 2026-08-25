# AGENTS.md

Python library scraping Siakang Untirta (Laravel + Livewire SIS) over pure HTTP. Managed with `uv`; Python 3.11+.

## Commands

```bash
uv run pytest -q                                # all tests (~60, offline)
uv run pytest tests/test_client_flow.py -k name # single test
uv run python examples/scrape_schedule.py       # CLI examples (need real creds in .env)
npm run dev                                     # docs dev server (VitePress, run in docs/)
```

No lint/typecheck config exists — pytest is the only gate.

## Testing

- All tests are **fully offline**: `tests/conftest.py` provides `FakeResponse`/fake session handlers keyed on `(method, url-predicate)` routes. Never make real network calls in tests; extend the handler lists instead.
- To test a new client code path, add a matching route tuple (`("GET"/"POST", url_predicate, responder_fn)`) in the test's handler list — see `standard_login_handlers` in conftest for the happy-path login flow.

## Gotchas

- `.env` at repo root holds real credentials (EMAIL/PASSWORD/SEMESTER). Never commit, print, or echo it.
- `.siakang_session_*.json` (from `SiakangClient(session_file=True)`) hold live login cookies — bearer credentials. Already gitignored; never print or commit them.
- `.siakang_class_cache.json` (default `FileCache` path) is a generated cache artifact, not source.
- The library **replays Livewire calls** rather than using a browser: parses `wire:snapshot` JSON from HTML via regex, POSTs property updates to `/livewire/update`, and reproduces `__lazyLoad` commits for detail pages/tabs (see `siakang/client.py`). Parsing is regex-based and brittle to upstream HTML changes — if a method breaks, suspect the page structure changed, not the logic.
- Login happens once in `SiakangClient.__enter__` (CSRF token from `/auth/login`, then POST credentials); all subsequent requests reuse that session's cookies. A failed login redirects back to `/auth/login` with HTTP 200 — status alone doesn't indicate failure.
- Cloudflare intermittently serves challenge pages; `_get_page` retries once after 1s. Preserve that behavior when touching fetch paths.
- Public API surface is re-exported in `siakang/__init__.py` (`__all__`) — add new public names there too.
