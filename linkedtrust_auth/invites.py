# Stateless, signed invite tokens.
#
# An invite is a self-contained token (HMAC-SHA256 signed) — no database row,
# no shared table. Any app that has the same LINKEDTRUST_INVITE_SECRET can
# verify it. That is what lets a SINGLE invite link work across multiple apps
# (Marten/Taiga, cases, ...) without those apps sharing a database or calling
# each other: they only share one secret.
#
# Payload fields:
#   e   - email the invite is bound to (optional; "" = any LinkedTrust account)
#   r   - role to grant (e.g. "volunteer")
#   a   - list of app slugs this invite is valid for (optional; [] = all apps)
#   x   - expiry, unix seconds
#   j   - random id (so two invites for the same person differ)

import base64
import hashlib
import hmac
import json

from . import settings as lt


class InviteError(Exception):
    pass


def _secret():
    secret = lt.get("LINKEDTRUST_INVITE_SECRET")
    if not secret:
        raise InviteError("LINKEDTRUST_INVITE_SECRET is not configured")
    return secret.encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def mint(email="", role="", apps=None, ttl_seconds=1209600, now=None, jti=""):
    """Create a signed invite token string. ttl defaults to 14 days.

    `now` (unix seconds) must be supplied by the caller — this module does not
    read the clock so it stays deterministic and testable. Management command
    and views pass time.time().
    """
    if now is None:
        raise InviteError("mint() requires now=<unix seconds>")
    if not role:
        role = lt.get("LINKEDTRUST_DEFAULT_ROLE")
    payload = {
        "e": (email or "").strip().lower(),
        "r": role,
        "a": apps or [],
        "x": int(now) + int(ttl_seconds),
        "j": jti,
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token, now, app_slug=None, email=None):
    """Validate a token. Returns the payload dict or raises InviteError.

    now       - unix seconds, supplied by caller (views pass time.time()).
    app_slug  - if set, token's app list (when non-empty) must include it.
    email     - if set (the authenticated user's email), and the token is
                bound to an email, they must match.
    """
    if not token or "." not in token:
        raise InviteError("Malformed invite")
    body, _, sig = token.partition(".")
    expected = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise InviteError("Invalid invite signature")

    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception:
        raise InviteError("Corrupt invite payload")

    if int(now) > int(payload.get("x", 0)):
        raise InviteError("Invite expired")

    allowed_apps = payload.get("a") or []
    if app_slug and allowed_apps and app_slug not in allowed_apps:
        raise InviteError("Invite not valid for this app")

    bound_email = (payload.get("e") or "").strip().lower()
    if bound_email and email and bound_email != (email or "").strip().lower():
        raise InviteError("Invite is for a different email")

    return payload
