---
title: "Mocking alpaca-py APIError with specific HTTP status codes"
category: integration-issues
tags: [alpaca-py, mocking, pytest, APIError, unit-testing]
module: broker.alpaca
symptom: "AttributeError when setting status_code on APIError"
root_cause: "APIError.status_code is a read-only property delegating to http_error.response.status_code"
date_solved: 2026-02-14
---

# Mocking alpaca-py APIError with specific HTTP status codes

## Problem

When writing unit tests for `AlpacaBrokerAdapter`, we needed to mock
`alpaca.common.exceptions.APIError` with specific HTTP status codes (e.g., 401,
403, 422) to test error handling branches. The naive approach of constructing an
`APIError` and assigning `status_code` directly fails because `status_code` is a
**read-only property**.

## Symptom

```python
from alpaca.common.exceptions import APIError

api_err = APIError("error")
api_err.status_code = 422  # raises AttributeError
```

Attempting to set `status_code` on an `APIError` instance raises
`AttributeError` because `status_code` is defined as a property on the class,
not a plain instance attribute.

## Investigation

1. **First attempt** -- Create `APIError("error")` and set `.status_code = 422`.
   Result: `AttributeError` because `status_code` is a property, not a settable
   attribute.

2. **Source inspection** -- Used `inspect.getsource(APIError)` to examine the
   actual class implementation inside alpaca-py.

3. **Discovery** -- `APIError.__init__(self, error, http_error=None)` accepts
   two arguments:
   - `error`: a JSON string (or plain message) describing the error.
   - `http_error`: an optional HTTP error object whose `.response.status_code`
     is read by the `status_code` property.

   The constructor stores `http_error` as `self._http_error`, and the
   `status_code` property reads from `self._http_error.response.status_code`.

## Solution

Create a `_make_api_error()` test helper that properly constructs the mock chain
so `APIError.status_code` returns the desired value:

```python
from unittest.mock import MagicMock

from alpaca.common.exceptions import APIError


def _make_api_error(status_code: int = 422, message: str = "error") -> APIError:
    """Create an APIError with the given status code for testing."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_http_error = MagicMock()
    mock_http_error.response = mock_response
    return APIError(message, http_error=mock_http_error)
```

### Usage in tests

```python
def test_authentication_error_handling():
    error = _make_api_error(status_code=401, message="unauthorized")
    assert error.status_code == 401

def test_forbidden_error_handling():
    error = _make_api_error(status_code=403, message="forbidden")
    assert error.status_code == 403

def test_validation_error_handling():
    error = _make_api_error(status_code=422, message="invalid order")
    assert error.status_code == 422
```

## Root Cause

alpaca-py defines `APIError.status_code` as a **read-only property** that
delegates to `self._http_error.response.status_code`. There is no setter, so
direct assignment raises `AttributeError`. The only way to control the status
code is to provide a properly shaped `http_error` object at construction time.

## Prevention

- When mocking third-party exceptions, always check whether the attributes you
  need to control are **properties** vs **plain attributes**. Properties require
  you to mock the underlying object they delegate to.
- Use `inspect.getsource()` or read the library source directly to understand
  the class internals before writing mock helpers.
- Wrap complex mock construction in a reusable helper function
  (e.g., `_make_api_error()`) so the pattern is documented once and used
  consistently across the test suite.
