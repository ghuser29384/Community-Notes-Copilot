from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from app.services.providers import ProviderError, request_form_json


X_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.x.com/2/oauth2/token"


@dataclass(frozen=True)
class OAuth2TokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str
    scope: str
    raw: dict


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def oauth2_authorize_url(client_id: str, redirect_uri: str, scopes: str, state: str, code_challenge: str) -> str:
    params = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        },
        quote_via=quote,
    )
    return f"{X_AUTHORIZE_URL}?{params}"


def _oauth_quote(value: object) -> str:
    return quote(str(value), safe="~-._")


def _oauth1_base_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("OAuth 1.0a requires an absolute HTTP(S) URL")
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    port = parsed.port
    include_port = port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443))
    netloc = f"{hostname}:{port}" if include_port else hostname
    return urlunsplit((scheme, netloc, parsed.path or "/", "", ""))


def oauth1_authorization_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
    *,
    nonce: str | None = None,
    timestamp: int | str | None = None,
) -> str:
    """Create an OAuth 1.0a HMAC-SHA1 Authorization header.

    Query parameters are included in the signature base string. JSON request-body
    fields are intentionally excluded, as required by OAuth 1.0a for non-form
    bodies. The caller must pass the final URL, including its query string.
    """

    required = {
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret,
        "access_token": access_token,
        "access_token_secret": access_token_secret,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing OAuth 1.0a credential fields: {', '.join(missing)}")

    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_urlsafe(24),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp if timestamp is not None else int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    query_params = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    signature_params = query_params + list(oauth_params.items())
    encoded_params = sorted((_oauth_quote(key), _oauth_quote(value)) for key, value in signature_params)
    normalized_params = "&".join(f"{key}={value}" for key, value in encoded_params)
    signature_base = "&".join(
        [
            method.upper(),
            _oauth_quote(_oauth1_base_url(url)),
            _oauth_quote(normalized_params),
        ]
    )
    signing_key = f"{_oauth_quote(consumer_secret)}&{_oauth_quote(access_token_secret)}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode("ascii"), signature_base.encode("ascii"), hashlib.sha1).digest()
    ).decode("ascii")
    oauth_params["oauth_signature"] = signature
    return "OAuth " + ", ".join(
        f'{_oauth_quote(key)}="{_oauth_quote(value)}"' for key, value in sorted(oauth_params.items())
    )


def exchange_oauth2_code(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> OAuth2TokenResponse:
    payload = request_form_json(
        "POST",
        X_TOKEN_URL,
        form={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        },
        basic_auth=(client_id, client_secret) if client_secret else None,
        timeout=30,
    )
    return _token_response(payload)


def refresh_oauth2_user_access_token(client_id: str, client_secret: str, refresh_token: str) -> OAuth2TokenResponse:
    payload = request_form_json(
        "POST",
        X_TOKEN_URL,
        form={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
        basic_auth=(client_id, client_secret) if client_secret else None,
        timeout=30,
    )
    return _token_response(payload, fallback_refresh_token=refresh_token)


def _token_response(payload: dict, fallback_refresh_token: str = "") -> OAuth2TokenResponse:
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise ProviderError("X OAuth token response did not include access_token")
    return OAuth2TokenResponse(
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or fallback_refresh_token),
        expires_in=int(payload.get("expires_in") or 0),
        token_type=str(payload.get("token_type") or "bearer"),
        scope=str(payload.get("scope") or ""),
        raw=payload,
    )
