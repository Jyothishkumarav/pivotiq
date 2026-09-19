"""Fyers API v3 client.

Docs: https://myapi.fyers.in/docsv3
Auth is a hash-based OAuth 2.0 code exchange; API calls use the header
`Authorization: {appId}:{access_token}` (colon-separated).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)


class FyersError(Exception):
    pass


class FyersTokenExpired(FyersError):
    """Raised when Fyers reports the access token is no longer valid."""


_AUTH_BASE = "https://api-t1.fyers.in/api/v3"
_DATA_BASE = "https://api-t1.fyers.in/data"

_EXPIRED_ERROR_MARKERS = ("please provide valid token", "token has expired", "invalid token")


def _app_id_hash() -> str:
    settings = get_settings()
    if not settings.fyers_app_id or not settings.fyers_secret:
        raise FyersError("Fyers is not configured. Set FYERS_APP_ID and FYERS_SECRET in .env.")
    raw = f"{settings.fyers_app_id}:{settings.fyers_secret}".encode()
    return hashlib.sha256(raw).hexdigest()


def build_login_url(state: str) -> str:
    settings = get_settings()
    if not settings.fyers_app_id:
        raise FyersError("FYERS_APP_ID is not configured.")
    params = {
        "client_id": settings.fyers_app_id,
        "redirect_uri": settings.fyers_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{_AUTH_BASE}/generate-authcode?{urllib.parse.urlencode(params)}"


def exchange_auth_code(auth_code: str) -> dict:
    """Trade the short-lived auth code for an access + refresh token."""
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": _app_id_hash(),
        "code": auth_code.strip(),
    }
    resp = requests.post(f"{_AUTH_BASE}/validate-authcode", json=payload, timeout=15)
    data = _parse(resp)
    if not data.get("access_token"):
        raise FyersError(data.get("message") or "No access_token in response")
    return data


def refresh_access_token(refresh_token: str, pin: str) -> dict:
    """Rotate the access token using the refresh token + a 4-digit PIN."""
    payload = {
        "grant_type": "refresh_token",
        "appIdHash": _app_id_hash(),
        "refresh_token": refresh_token,
        "pin": pin,
    }
    resp = requests.post(f"{_AUTH_BASE}/validate-refresh-token", json=payload, timeout=15)
    return _parse(resp)


def _auth_header(access_token: str) -> dict[str, str]:
    settings = get_settings()
    return {"Authorization": f"{settings.fyers_app_id}:{access_token}"}


def get_profile(access_token: str) -> dict:
    resp = requests.get(f"{_AUTH_BASE}/profile", headers=_auth_header(access_token), timeout=15)
    return _parse(resp)


def get_funds(access_token: str) -> dict:
    resp = requests.get(f"{_AUTH_BASE}/funds", headers=_auth_header(access_token), timeout=15)
    return _parse(resp)


def get_holdings(access_token: str) -> dict:
    resp = requests.get(f"{_AUTH_BASE}/holdings", headers=_auth_header(access_token), timeout=15)
    return _parse(resp)


def get_positions(access_token: str) -> dict:
    resp = requests.get(f"{_AUTH_BASE}/positions", headers=_auth_header(access_token), timeout=15)
    return _parse(resp)


def nse_symbol(symbol: str) -> str:
    """Map a bare NSE ticker (`TCS`) to Fyers' format (`NSE:TCS-EQ`)."""
    return f"NSE:{symbol.upper()}-EQ"


def get_quotes(access_token: str, symbols: list[str]) -> dict:
    """Batch quotes for up to 50 symbols. Uses Fyers `NSE:XXX-EQ` symbol format."""
    if not symbols:
        return {"s": "ok", "d": []}
    joined = ",".join(nse_symbol(s) for s in symbols[:50])
    resp = requests.get(
        f"{_DATA_BASE}/quotes",
        headers=_auth_header(access_token),
        params={"symbols": joined},
        timeout=15,
    )
    return _parse(resp)


def get_history(
    access_token: str,
    symbol: str,
    resolution: str = "D",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Fetch OHLCV candles. `resolution` = 'D' (daily), '1', '5', '15', '30', '60' (minutes)."""
    params: dict[str, str | int] = {
        "symbol": nse_symbol(symbol),
        "resolution": resolution,
        "date_format": "1",
        "cont_flag": "1",
    }
    if date_from:
        params["range_from"] = date_from
    if date_to:
        params["range_to"] = date_to
    resp = requests.get(
        f"{_DATA_BASE}/history",
        headers=_auth_header(access_token),
        params=params,
        timeout=20,
    )
    return _parse(resp)


def _parse(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:
        raise FyersError(f"Fyers returned non-JSON: {resp.text[:200]}") from exc

    message = str(data.get("message") or "").lower()
    if data.get("s") == "error" or (resp.status_code >= 400 and data.get("s") != "ok"):
        if resp.status_code == 401 or any(marker in message for marker in _EXPIRED_ERROR_MARKERS):
            raise FyersTokenExpired(data.get("message") or "Fyers session expired")
        raise FyersError(data.get("message") or f"Fyers HTTP {resp.status_code}")
    return data


def parse_access_token_expiry(access_token: str) -> datetime | None:
    """Fyers issues JWT-encoded access tokens whose `exp` claim is the real
    expiry (usually ~06:00 IST next). Prefer it over any wall-clock estimate."""
    try:
        payload_part = access_token.split(".")[1]
        padded = payload_part + "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = payload.get("exp")
        if not exp:
            return None
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except Exception as exc:
        logger.warning("Could not parse Fyers token exp claim: %s", exc)
        return None
