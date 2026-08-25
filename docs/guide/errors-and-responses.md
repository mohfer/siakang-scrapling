# Errors & Responses

Wrap any call with the `api_response` decorator so consumers always receive the
same envelope — `{code, message, data}` — instead of raw exceptions.

```python
from siakang import SiakangClient, api_response

@api_response
def fetch_schedule(email: str, password: str, semester: str | None):
    with SiakangClient(email, password) as client:
        return client.get_schedule(semester=semester)

response = fetch_schedule("xxx@student.untirta.ac.id", "...", "20252")
response.ok            # True when code == 200
response.to_dict()     # {"code": ..., "message": ..., "data": ...}
```

## Envelope

| Field | Type | Description |
|---|---|---|
| `code` | `int` | Status code (see table) |
| `message` | `str` | Human-readable summary |
| `data` | any | The payload on success; `None` on failure |

## Error Codes

Error codes mirror HTTP semantics:

| Code | Exception | Meaning |
|---|---|---|
| 200 | — | Success |
| 400 | `SiakangError` | Usage error (e.g. client used without `with`) |
| 401 | `SiakangAuthError` | Wrong credentials or expired session |
| 404 | `SiakangNotFoundError` | Requested semester does not exist |
| 500 | any other exception | Unexpected internal error (message is sanitised) |
| 502 | `SiakangUpstreamError` | Siakang server failure or page structure changed |

The exception hierarchy:

```
SiakangError
├── SiakangAuthError        # 401
├── SiakangNotFoundError    # 404
└── SiakangUpstreamError    # 502 — HTTP failures, Cloudflare challenges,
                            #      Livewire component mismatches
```

Catch `SiakangError` to handle every library-raised failure at once; catch the
subclasses when you need finer-grained behaviour.
