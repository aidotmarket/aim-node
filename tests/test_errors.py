from __future__ import annotations

from aim_node.management.errors import ERROR_HTTP_STATUS, ErrorCode, make_error, make_market_error


def _all_error_codes() -> set[str]:
    return {
        value
        for name, value in vars(ErrorCode).items()
        if not name.startswith("_") and isinstance(value, str)
    }


def test_make_error_sets_request_id():
    err = make_error(ErrorCode.NOT_FOUND, "Missing")
    assert isinstance(err.request_id, str)
    assert err.request_id.startswith("req_")
    assert len(err.request_id) > 4


def test_make_error_retryable_true():
    err = make_error(ErrorCode.MARKET_TIMEOUT, "Timed out")
    assert err.retryable is True


def test_make_error_retryable_false():
    err = make_error(ErrorCode.NOT_FOUND, "Missing")
    assert err.retryable is False


def test_make_market_error_shape():
    err = make_market_error(502, "upstream bad gateway", "/api/v1/listings")
    assert err.model_dump(exclude_none=True) == {
        "code": "market_error",
        "message": "Marketplace returned an error",
        "details": {
            "status": 502,
            "backend_error": "upstream bad gateway",
            "endpoint": "/api/v1/listings",
        },
        "retryable": False,
        "request_id": err.request_id,
        "suggested_action": "Check your API key in Settings",
    }
    assert isinstance(err.request_id, str)
    assert err.request_id.startswith("req_")


def test_error_http_status_complete():
    assert _all_error_codes() == set(ERROR_HTTP_STATUS)
