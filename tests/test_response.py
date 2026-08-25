"""Unit tests: the {code, message, data} API response envelope."""

from siakang import SiakangError, api_response
from siakang.client import (
    SiakangAuthError,
    SiakangNotFoundError,
    SiakangUpstreamError,
)


@api_response
def _ok():
    return {"rows": [1, 2]}


@api_response
def _auth():
    raise SiakangAuthError("Login failed")


@api_response
def _not_found():
    raise SiakangNotFoundError("Semester X not found")


@api_response
def _upstream():
    raise SiakangUpstreamError("livewire/update HTTP 500")


@api_response
def _usage():
    raise SiakangError("Client is not open")


@api_response
def _boom():
    raise ValueError("oops")


class TestEnvelope:
    def test_success_shape(self):
        r = _ok()
        assert r.ok is True
        assert r.code == 200
        assert r.message == "Success"
        assert r.to_dict() == {"code": 200, "message": "Success", "data": {"rows": [1, 2]}}

    def test_auth_maps_to_401(self):
        r = _auth()
        assert (r.code, r.ok) == (401, False)
        assert "Login failed" in r.message

    def test_not_found_maps_to_404(self):
        r = _not_found()
        assert (r.code, r.ok) == (404, False)

    def test_upstream_maps_to_502(self):
        r = _upstream()
        assert (r.code, r.ok) == (502, False)
        assert "500" in r.message

    def test_usage_error_maps_to_400(self):
        r = _usage()
        assert r.code == 400

    def test_unexpected_is_sanitised_to_500(self):
        r = _boom()
        assert r.code == 500
        assert "oops" in r.message

    def test_kwargs_and_wraps_preserved(self):
        @api_response
        def add(a, b=0):
            """docs"""
            return a + b

        assert add(1, b=2).data == 3
        assert add.__name__ == "add"
        assert add.__doc__ == "docs"
