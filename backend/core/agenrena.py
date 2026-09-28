"""Agenrena Business Integration API, called as this App's Vendor.

Vendor credentials authenticate the App; each call that acts for a store names
that store's grant in ``X-Grant-Id``. See docs/agent.md for the flow. Standard
library only: this is a handful of JSON calls.
"""

import hashlib
import json
import urllib.error
import urllib.request
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

TIMEOUT_SECONDS = 10
SCOPES = ["messages:send"]
# Agenrena's answers to the grant named in a call. Either means "stop using it".
GRANT_GONE = {"INTEGRATION_GRANT_REVOKED", "INTEGRATION_GRANT_INVALID"}


class AgenrenaError(Exception):
    def __init__(self, code, status=None):
        self.code = code
        self.status = status
        super().__init__(f"{status} {code}")


def configured():
    return bool(settings.AGENRENA_VENDOR_ID and settings.AGENRENA_VENDOR_SECRET)


def start_authorization():
    """Open a consent session. The link is single-use and expires in minutes."""
    return _call("POST", "/api/business-api/authorize/start/", {"scopes": SCOPES})


def authorization(session_id):
    return _call("GET", f"/api/business-api/authorize/session/{quote(str(session_id))}/")


def release_grant(grant_id):
    """Hand a grant back, as the store's owner disconnecting it from this App."""
    try:
        _call("DELETE", f"/api/business-api/grants/{quote(grant_id, safe='')}/")
    except AgenrenaError as exc:
        if exc.code not in GRANT_GONE:
            raise


def send_message(grant_id, customer_ref, text, *, card=None, client_message_id=""):
    body = {"customer_ref": customer_ref, "text": text}
    if card is not None:
        body["card"] = card
    if client_message_id:
        body["client_message_id"] = client_message_id
    return _call("POST", "/api/business-api/messages/send/", body, grant_id=grant_id)


def _call(method, path, body=None, *, grant_id=""):
    status, payload = _request(method, path, body, token=_token(), grant_id=grant_id)
    if status == 401 or (status == 403 and _code(payload) == "INTEGRATION_TOKEN_INVALID"):
        # Tokens are per Vendor and short-lived. Refresh once, then report.
        cache.delete(_token_key())
        status, payload = _request(method, path, body, token=_token(), grant_id=grant_id)
    if not 200 <= status < 300:
        raise AgenrenaError(_code(payload) or f"HTTP_{status}", status)
    return payload


def _token():
    if not configured():
        raise AgenrenaError("NOT_CONFIGURED")
    key = _token_key()
    token = cache.get(key)
    if token:
        return token
    status, payload = _request(
        "POST",
        "/api/business-api/token/",
        {
            "vendor_id": settings.AGENRENA_VENDOR_ID,
            "vendor_secret": settings.AGENRENA_VENDOR_SECRET,
        },
    )
    if status != 200:
        raise AgenrenaError(_code(payload) or f"HTTP_{status}", status)
    expires = parse_datetime(str(payload.get("expires_at", "")))
    token = payload.get("access_token")
    if not token or expires is None:
        raise AgenrenaError("INVALID_TOKEN_RESPONSE", status)
    cache.set(key, token, timeout=max(1, int((expires - timezone.now()).total_seconds()) - 60))
    return token


def _token_key():
    # Changes with the secret, so a rotated secret never reuses an old token.
    identity = "\n".join(
        [settings.AGENRENA_BASE_URL, settings.AGENRENA_VENDOR_ID, settings.AGENRENA_VENDOR_SECRET]
    )
    return "agenrena-token:" + hashlib.sha256(identity.encode()).hexdigest()


def _request(method, path, body=None, *, token="", grant_id=""):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if grant_id:
        headers["X-Grant-Id"] = grant_id
    request = urllib.request.Request(
        settings.AGENRENA_BASE_URL + path,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, _json(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _json(exc.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AgenrenaError("UNAVAILABLE") from exc


def _json(raw):
    try:
        value = json.loads(raw or b"{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _code(payload):
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    # Field errors carry the specific reason, e.g. CUSTOMER_NOT_FOUND.
    for problems in (error.get("fields") or {}).values():
        if problems and isinstance(problems[0], dict) and problems[0].get("code"):
            return problems[0]["code"]
    return error.get("code", "")
