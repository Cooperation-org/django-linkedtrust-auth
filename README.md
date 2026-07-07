# django-linkedtrust-auth

LinkedTrust OIDC authentication for Django applications (Taiga, etc.).

Server-side OIDC flow: the browser redirects to your Django backend, which handles the entire IdP interaction and redirects back to your frontend with tokens in the URL fragment.

## Setup

### 1. Install

```bash
pip install git+https://github.com/Cooperation-org/django-linkedtrust-auth.git
```

### 2. Register an OIDC client with LinkedTrust

Ask for a client to be created at `https://live.linkedtrust.us` with:
- **type:** confidential
- **redirect_uri:** `https://YOUR-BACKEND/api/v1/auth/linkedtrust/callback`
- **scopes:** `openid email profile trust`

You'll receive a `client_id` and `client_secret`.

### 3. Django settings

```python
# settings.py or settings/config.py

INSTALLED_APPS += ["linkedtrust_auth"]

# LinkedTrust IdP
LINKEDTRUST_URL = "https://live.linkedtrust.us"
LINKEDTRUST_CLIENT_ID = "lt_your_client_id"
LINKEDTRUST_CLIENT_SECRET = os.environ.get("LINKEDTRUST_CLIENT_SECRET", "")

# Where to send the browser after login
LINKEDTRUST_FRONTEND_URL = "https://your-frontend.example.com"
LINKEDTRUST_FRONTEND_CALLBACK = "/oauth/callback"   # frontend route that reads tokens

# User handler — receives OIDC userinfo dict, returns (user, tokens_dict)
LINKEDTRUST_USER_HANDLER = "linkedtrust_auth.taiga_adapter.get_or_create_user"  # for Taiga
```

For non-Taiga apps, point `LINKEDTRUST_USER_HANDLER` at your own function:

```python
def get_or_create_user(userinfo):
    """
    userinfo has: email, name, preferred_username, sub, etc.
    Return (user_object, {"auth_token": "...", "refresh": "...", ...})
    """
    ...
```

### 4. URL routing

```python
# urls.py
from django.urls import path, include

urlpatterns = [
    path("api/v1/auth/linkedtrust/", include("linkedtrust_auth.urls")),
    # ... your other routes
]
```

### 5. Store the client secret securely

Create a `.env` file (mode 600) with:

```
LINKEDTRUST_CLIENT_SECRET=your-secret-here
```

If using systemd, add to your service unit:

```ini
EnvironmentFile=/path/to/your/.env
```

Then `sudo systemctl daemon-reload && sudo systemctl restart your-service`.

### 6. Nginx — ensure HTTPS scheme is forwarded

If your Django app is behind a reverse proxy with TLS terminated upstream:

```nginx
proxy_set_header X-Forwarded-Proto https;
```

And in Django settings (usually already present):

```python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

### 7. Frontend

Your frontend login button just navigates to the backend:

```js
window.location.href = `${API_BASE}/auth/linkedtrust/redirect`;
```

Your frontend callback page (`/oauth/callback`) reads tokens from the URL fragment:

```js
const hash = window.location.hash.slice(1);
const params = new URLSearchParams(hash);
const authToken = params.get('auth_token');
const refresh = params.get('refresh');

if (authToken) {
  // Store tokens and redirect to app
  window.history.replaceState(null, '', window.location.pathname);
  // ... save authToken, navigate to '/'
}
```

## Invite links (one link per volunteer, works across apps)

Invites are **stateless signed tokens** — no database table, no shared storage. Every app that sets the **same** `LINKEDTRUST_INVITE_SECRET` can verify the same token, so **one link works at every app** (Marten, cases, ...) without those apps sharing a database or calling each other.

### 1. Settings (add to each app)

```python
LINKEDTRUST_INVITE_SECRET = os.environ.get("LINKEDTRUST_INVITE_SECRET", "")  # SAME value on every app
LINKEDTRUST_REQUIRE_INVITE = True     # only invited people may create an account
LINKEDTRUST_DEFAULT_ROLE = "volunteer"
LINKEDTRUST_APP_SLUG = "marten"       # or "cases" — lets you scope an invite to specific apps
```

`LINKEDTRUST_REQUIRE_INVITE` defaults to `False`, so existing login-only deployments are unaffected until you opt in.

### 2. Mint a link

CLI:

```bash
python manage.py lt_mint_invite --email jane@example.org --role volunteer \
    --apps marten,cases --base https://help.raisethevoices.org --days 14
```

prints:

```
https://help.raisethevoices.org/api/v1/auth/linkedtrust/redirect?invite=<token>
```

Send that one link to the volunteer. Because both apps share the secret, the **same token also logs them into cases** — either give them the one link (it lands on Marten, and cases recognizes them on first "Sign in with LinkedTrust"), or build the cases link with `--base https://cases.raisethevoices.org`.

Or use the built-in admin page: **`/api/v1/auth/linkedtrust/invites/`** (staff/superuser only) — a one-field form that generates the link to copy.

### 3. What enforcement happens on callback

- Signature + expiry checked.
- If the invite is bound to an email, the authenticated LinkedTrust email must match.
- If `--apps` was set, the token is only accepted at those `LINKEDTRUST_APP_SLUG`s.
- If `LINKEDTRUST_REQUIRE_INVITE = True` and no valid invite is present, account creation is refused (redirect to `/login?error=invite_required`).

The verified invite payload (`{e, r, a, x, j}`) is passed to your `LINKEDTRUST_USER_HANDLER` as `userinfo["invite"]`, so your adapter can assign the role / project memberships.

## How it works

1. **Frontend** → `GET /api/v1/auth/linkedtrust/redirect`
2. **Django** stores CSRF state in session, **302** → IdP authorize endpoint
3. **User** authenticates at IdP (Google, Bluesky, or LinkedTrust account)
4. **IdP** → `GET /api/v1/auth/linkedtrust/callback?code=...&state=...`
5. **Django** verifies state, exchanges code for IdP tokens, fetches userinfo, finds/creates local user, mints app tokens
6. **Django 302** → `https://your-frontend/oauth/callback#auth_token=...&refresh=...`
7. **Frontend** reads fragment, stores tokens, done

Tokens are passed in the URL **fragment** (after `#`), not query params — fragments are never sent to servers, so they don't appear in logs.

## Architecture

```
linkedtrust_auth/
├── oidc.py            # Core OIDC: authorize URL, code exchange, userinfo (pure Python + requests)
├── views.py           # Django views: RedirectView, CallbackView
├── urls.py            # URL routing
├── settings.py        # Settings with defaults
├── taiga_adapter.py   # Taiga-specific user handler
└── apps.py            # Django AppConfig
```

`oidc.py` has no Django dependency beyond reading settings — it can be reused in non-Django Python apps (e.g., Odoo addons) by passing config values directly.
