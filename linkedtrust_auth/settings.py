# Default settings — override in your Django settings module.
from django.conf import settings

DEFAULTS = {
    "LINKEDTRUST_URL": "",
    "LINKEDTRUST_CLIENT_ID": "",
    "LINKEDTRUST_CLIENT_SECRET": "",
    "LINKEDTRUST_SCOPES": "openid email profile trust",
    "LINKEDTRUST_FRONTEND_URL": "",          # where to redirect browser after login
    "LINKEDTRUST_FRONTEND_CALLBACK": "/oauth/callback",  # path on frontend that receives tokens
    "LINKEDTRUST_REDIRECT_URI": "",           # fixed callback URL (must be registered on the IdP); overrides auto-build

    # --- Invite links (optional; login works without any of these) ---
    "LINKEDTRUST_INVITE_SECRET": "",         # shared HMAC secret; SAME value on every app that honors the invite
    "LINKEDTRUST_REQUIRE_INVITE": False,     # if True, only users with a valid invite may create an account
    "LINKEDTRUST_DEFAULT_ROLE": "volunteer", # role stamped on invites/users when none is given
    "LINKEDTRUST_APP_SLUG": "",              # this app's slug (e.g. "marten", "cases"); used to scope invites
}


def get(name):
    return getattr(settings, name, DEFAULTS.get(name, ""))
