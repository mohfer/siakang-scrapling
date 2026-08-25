# How It Works

Understanding the internals helps when Siakang changes and something breaks.

## Authentication

1. `GET /auth/login` — the page carries a Laravel CSRF token in a hidden
   `_token` input.
2. `POST /auth/login` with the token + credentials. A successful login sets the
   session cookie; note that on success Laravel redirects to the *previous* URL,
   which is why requests always carry an explicit `Referer`.
3. `GET /dashboard/dashboard-akademik` verifies the session landed on a real
   dashboard (a failed login lands back on `/auth/login` with HTTP 200, so the
   URL is checked rather than the status code).

All of this runs through `FetcherSession` (curl-cffi) with browser TLS
impersonation, which is enough for the site's lightweight Cloudflare layer.

## Livewire Replay

Most Siakang pages are [Livewire](https://livewire.laravel.com) components. The
library never runs JavaScript; instead it replays the HTTP calls Livewire makes:

1. **Snapshots** — every component embeds its serialised state in a
   `wire:snapshot` attribute (HTML-escaped JSON). Attribute quoting switches
   between single and double quotes depending on content, so both are parsed.
2. **Updates** — property changes are sent to `/livewire/update` as
   `{"snapshot": ..., "updates": {...}, "calls": []}`. Switching the schedule
   list view is just `{"selected": "card"}` / `{"mode": "card"}`.
3. **Lazy components** (`__lazyLoad`) — detail-page content mounts lazily. Each
   lazy component ships its mount params as a base64-encoded
   `__mountParamsContainer` snapshot inside `$wire.__lazyLoad('...')`. Replaying
   that call returns the fully rendered HTML, including nested lazy children.

## Detail Pages

`get_detail()` composes three kinds of commits:

| Piece | Mechanism |
|---|---|
| Header (Kode Jadwal, Kelas, ...) | `__lazyLoad` on `pengajaran.detail-kuliah` |
| Participants tab | `__lazyLoad` on `jadwal.peserta` |
| RPS / Journal / Recap tabs | set `active_menu`, then hydrate the child that appears (recursively) |

## Class Letters

The parallel class only appears in the detail header. Since it belongs to the
course offering (not the student), letters are cached by `schedule_id` and
fetched for all courses in parallel threads with shared cookies.
