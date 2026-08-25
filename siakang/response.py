"""Consistent API response envelope: {code, message, data}.

Wrap any client call with the ``api_response`` decorator (or build an
``ApiResponse`` directly) so every consumer of this library receives the
same shape, whether the call succeeded or failed:

    {"code": 200, "message": "Success", "data": [...]}

Error codes mirror HTTP semantics:
    200 success · 400 bad request/usage · 401 auth failed
    404 not found · 500 unexpected error · 502 Siakang upstream failure
"""

from functools import wraps
from typing import Any

from .client import (
    SiakangAuthError,
    SiakangError,
    SiakangNotFoundError,
    SiakangUpstreamError,
)

CODE_OK = 200
CODE_BAD_REQUEST = 400
CODE_UNAUTHORIZED = 401
CODE_NOT_FOUND = 404
CODE_SERVER_ERROR = 500
CODE_UPSTREAM = 502


class ApiResponse:
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data

    @property
    def ok(self) -> bool:
        return self.code == CODE_OK

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "data": self.data}

    def __repr__(self):
        return f"ApiResponse(code={self.code}, message={self.message!r})"


def success(data: Any = None, message: str = "Success") -> ApiResponse:
    return ApiResponse(CODE_OK, message, data)


def error(message: str, code: int = CODE_SERVER_ERROR, data: Any = None) -> ApiResponse:
    return ApiResponse(code, message, data)


def api_response(func):
    """Decorator turning a siakang call into an ApiResponse.

    Usage:
        @api_response
        def fetch_schedule(email, password, semester):
            with SiakangClient(email, password) as c:
                return c.get_schedule(semester)
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> ApiResponse:
        try:
            return success(func(*args, **kwargs))
        except SiakangAuthError as e:
            return ApiResponse(CODE_UNAUTHORIZED, str(e))
        except SiakangNotFoundError as e:
            return ApiResponse(CODE_NOT_FOUND, str(e))
        except SiakangUpstreamError as e:
            return ApiResponse(CODE_UPSTREAM, f"Siakang upstream failure — try again later ({e})")
        except SiakangError as e:
            return ApiResponse(CODE_BAD_REQUEST, str(e))
        except Exception as e:  # noqa: BLE001 - never leak raw exceptions to consumers
            return ApiResponse(CODE_SERVER_ERROR, f"Unexpected error: {e}")

    return wrapper
