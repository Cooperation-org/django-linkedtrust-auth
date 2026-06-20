# django-linkedtrust-auth

LinkedTrust OIDC authentication for Django applications.

Server-side OIDC flow: the browser redirects to your Django backend, which handles the entire IdP interaction and redirects back to your frontend with tokens.

## Quick start

```bash
pip install django-linkedtrust-auth
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS += ["linkedtrust_auth"]
```

Add URL routes:

```python
# urls.py
from django.urls import path, include

urlpatterns += [
    path("api/v1/auth/linkedtrust/", include("linkedtrust_auth.urls")),
]
```

Configure settings:

```python
LINKEDTRUST_URL = "https://live.linkedtrust.us"
LINKEDTRUST_CLIENT_ID = "your-client-id"
LINKEDTRUST_CLIENT_SECRET = "your-client-secret"
LINKEDTRUST_FRONTEND_URL = "https://your-frontend.example.com"
LINKEDTRUST_FRONTEND_CALLBACK = "/oauth/callback"  # frontend route that reads tokens from fragment
LINKEDTRUST_USER_HANDLER = "your_app.auth.get_or_create_user"  # dotted path
```

The `LINKEDTRUST_USER_HANDLER` function receives OIDC userinfo dict and must return `(user, tokens_dict)`.

### Taiga adapter

For Taiga, use the built-in adapter:

```python
LINKEDTRUST_USER_HANDLER = "linkedtrust_auth.taiga_adapter.get_or_create_user"
```

## Flow

1. Frontend: `window.location.href = "/api/v1/auth/linkedtrust/redirect"`
2. Django 302s to IdP authorize endpoint
3. User authenticates at IdP
4. IdP redirects to Django callback
5. Django exchanges code for tokens, fetches userinfo, creates/finds user
6. Django redirects to frontend with app tokens in URL fragment
