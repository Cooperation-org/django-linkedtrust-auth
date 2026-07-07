# Generic clean-Django adapter: turn OIDC userinfo into (user, tokens).
#
# Usage in settings:
#   LINKEDTRUST_USER_HANDLER = "linkedtrust_auth.cases_adapter.get_or_create_user"
#
# This fits a normal Django app (stock django.contrib.auth.User OR a custom
# AUTH_USER_MODEL, resolved via get_user_model()). It:
#   - finds or creates the user by email (eager creation on first login),
#   - stamps first/last name and marks the account active with no usable password,
#   - honors an invite role if the model has a place to put it,
#   - issues API tokens, auto-detecting SimpleJWT then DRF authtoken.
#
# THREE THINGS TO CONFIRM against the real cases app (marked CONFIRM below):
#   1. User model + which fields exist (first_name/last_name vs. full_name, role field).
#   2. Token scheme — SimpleJWT / DRF authtoken / session. _issue_tokens covers the
#      first two; if cases uses plain Django sessions, replace _issue_tokens with a
#      django.contrib.auth.login(request, user) call (needs the request — subclass
#      CallbackView instead of using this hook).
#   3. What the frontend callback page reads (the keys in the returned dict become
#      the URL fragment the frontend parses).

import logging
import uuid

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


@transaction.atomic
def get_or_create_user(userinfo):
    from django.contrib.auth import get_user_model

    User = get_user_model()

    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        raise ValueError("LinkedTrust account has no email address")

    full_name = (
        userinfo.get("name")
        or userinfo.get("preferred_username")
        or email.split("@")[0]
    )
    first, _, last = full_name.partition(" ")

    try:
        user = User.objects.get(email__iexact=email)
        created = False
    except User.DoesNotExist:
        username = _unique_username(User, email)
        fields = {"email": email}
        # CONFIRM(1): name fields. Stock Django = first_name/last_name.
        if _has_field(User, "first_name"):
            fields["first_name"] = first[:150]
        if _has_field(User, "last_name"):
            fields["last_name"] = last[:150]
        if _has_field(User, "full_name"):
            fields["full_name"] = full_name
        # Set the username field (may be "username" or "email").
        username_field = getattr(User, "USERNAME_FIELD", "username")
        if username_field == "username" and _has_field(User, "username"):
            fields["username"] = username

        user = User(**fields)
        if _has_field(User, "is_active"):
            user.is_active = True
        user.set_unusable_password()  # login is only ever via LinkedTrust
        try:
            user.save()
        except IntegrityError:
            raise ValueError("Could not create account - please try again")
        created = True

    # CONFIRM(1, optional): apply invite role if the model has a role field.
    invite = userinfo.get("invite") or {}
    role = invite.get("r")
    if role and _has_field(User, "role") and (created or not getattr(user, "role", None)):
        user.role = role
        user.save(update_fields=["role"])

    tokens = _issue_tokens(user)
    return user, tokens


def _has_field(model, name):
    return name in {f.name for f in model._meta.get_fields()}


def _unique_username(User, email):
    base = email.split("@")[0].replace(".", "_").replace("+", "_")[:24] or "user"
    username = base
    suffix = 1
    while User.objects.filter(username__iexact=username).exists():
        username = f"{base}_{suffix}"
        suffix += 1
    return username


def _issue_tokens(user):
    """CONFIRM(2): return whatever the cases frontend expects. Auto-detects the
    two common DRF schemes; raises a clear error if neither is installed."""
    # SimpleJWT
    try:
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        return {"auth_token": str(refresh.access_token), "refresh": str(refresh)}
    except ImportError:
        pass

    # DRF authtoken
    try:
        from rest_framework.authtoken.models import Token
        token, _ = Token.objects.get_or_create(user=user)
        return {"auth_token": token.key}
    except ImportError:
        pass

    raise RuntimeError(
        "cases_adapter: no supported token backend found. Install SimpleJWT or "
        "DRF authtoken, or replace _issue_tokens() with the scheme cases uses."
    )
