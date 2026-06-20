# Taiga-specific adapter: bridges linkedtrust_auth with Taiga's auth system.
#
# Usage in settings/config.py:
#   LINKEDTRUST_USER_HANDLER = "linkedtrust_auth.taiga_adapter.get_or_create_user"

import uuid
import logging

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


@transaction.atomic
def get_or_create_user(userinfo):
    """
    Find or create a Taiga user from OIDC userinfo, return (user, tokens_dict).
    tokens_dict is what the frontend needs to authenticate with Taiga's API.
    """
    from django.contrib.auth import get_user_model
    from taiga.auth.services import make_auth_response_data

    User = get_user_model()

    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        raise ValueError("LinkedTrust account has no email address")

    full_name = (
        userinfo.get("name")
        or userinfo.get("preferred_username")
        or email.split("@")[0]
    )

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        base_username = email.split("@")[0].replace(".", "_").replace("+", "_")[:24]
        username = base_username
        suffix = 1
        while User.objects.filter(username__iexact=username).exists():
            username = f"{base_username}_{suffix}"
            suffix += 1

        user = User(
            username=username,
            email=email,
            full_name=full_name,
            verified_email=True,
            email_token=str(uuid.uuid4()),
            new_email=email,
            read_new_terms=True,
        )
        user.set_unusable_password()

        try:
            user.save()
        except IntegrityError:
            raise ValueError("Could not create account - please try again")

    tokens = make_auth_response_data(user)
    return user, tokens
