# Core OIDC operations — no framework-specific dependencies beyond Django settings.
import logging
import requests
from . import settings as lt

logger = logging.getLogger(__name__)


class OIDCError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def authorize_url(redirect_uri, state):
    """Build the IdP authorize URL for a browser redirect."""
    issuer = lt.get("LINKEDTRUST_URL").rstrip("/")
    client_id = lt.get("LINKEDTRUST_CLIENT_ID")
    scopes = lt.get("LINKEDTRUST_SCOPES")

    if not issuer or not client_id:
        raise OIDCError("LINKEDTRUST_URL and LINKEDTRUST_CLIENT_ID must be configured")

    from urllib.parse import urlencode
    params = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
    })
    return f"{issuer}/oauth/authorize?{params}"


def exchange_code(code, redirect_uri):
    """Exchange an authorization code for tokens at the IdP."""
    issuer = lt.get("LINKEDTRUST_URL").rstrip("/")
    client_id = lt.get("LINKEDTRUST_CLIENT_ID")
    client_secret = lt.get("LINKEDTRUST_CLIENT_SECRET")

    resp = requests.post(
        f"{issuer}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )

    if resp.status_code != 200:
        logger.error("LinkedTrust token exchange failed: %s %s", resp.status_code, resp.text[:500])
        raise OIDCError("Token exchange failed")

    return resp.json()


def get_userinfo(access_token):
    """Fetch user profile from the IdP's userinfo endpoint."""
    issuer = lt.get("LINKEDTRUST_URL").rstrip("/")

    resp = requests.get(
        f"{issuer}/oauth/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )

    if resp.status_code != 200:
        logger.error("LinkedTrust userinfo failed: %s %s", resp.status_code, resp.text[:500])
        raise OIDCError("Failed to fetch user profile")

    return resp.json()
