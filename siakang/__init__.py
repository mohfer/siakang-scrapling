"""siakang — library for scraping Siakang Untirta over pure HTTP."""

from .client import (
    BASE,
    SiakangAuthError,
    SiakangClient,
    SiakangError,
    SiakangNotFoundError,
    SiakangUpstreamError,
)
from .response import ApiResponse, api_response

__all__ = [
    "SiakangClient",
    "SiakangError",
    "SiakangAuthError",
    "SiakangNotFoundError",
    "SiakangUpstreamError",
    "ApiResponse",
    "api_response",
    "BASE",
]
