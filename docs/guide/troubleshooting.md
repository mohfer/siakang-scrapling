# Troubleshooting

## "Login failed — check email/password"

The login POST silently lands back on `/auth/login`. Credentials are wrong,
expired, or the account is locked.

## "Livewire components changed / not found"

Siakang was updated and a component name no longer matches. Compare the new
`wire:snapshot` names in the page against the ones expected in
`siakang/client.py`.

## Error 502 / "livewire/update HTTP 500"

The Siakang server failed to render something. Some tabs legitimately fail
(e.g. the journal tab when no sessions exist). Retry later; if it persists the
page structure probably changed.

## Wrong semester returned

- Passing `semester=None` means *whatever this session currently has selected* —
  earlier calls with `change-semester` affect later calls on the same client.
- When using dotenv, remember `load_dotenv()` does **not** override variables
  already present in the shell (`echo $SEMESTER` to check).

## Empty grades (IP/IPK/score are null)

Grades simply have not been published for that semester yet. Check an older
semester to confirm parsing works.

## Cloudflare challenge pages

Rare over plain HTTP. `_get_page` detects them and retries once; repeated
failures surface as `SiakangUpstreamError`.

## Running from another machine

`examples/` scripts expect `.env` in the working directory. The library itself
has no filesystem dependencies.
