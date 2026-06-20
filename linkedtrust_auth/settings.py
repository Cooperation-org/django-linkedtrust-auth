# Default settings — override in your Django settings module.
from django.conf import settings

DEFAULTS = {
    "LINKEDTRUST_URL": "",
    "LINKEDTRUST_CLIENT_ID": "",
    "LINKEDTRUST_CLIENT_SECRET": "",
    "LINKEDTRUST_SCOPES": "openid email profile trust",
    "LINKEDTRUST_FRONTEND_URL": "",          # where to redirect browser after login
    "LINKEDTRUST_FRONTEND_CALLBACK": "/oauth/callback",  # path on frontend that receives tokens
}


def get(name):
    return getattr(settings, name, DEFAULTS.get(name, ""))
