# Taiga-specific adapter: bridges linkedtrust_auth with Taiga's auth system.
#
# Usage in settings/config.py:
#   LINKEDTRUST_USER_HANDLER = "linkedtrust_auth.taiga_adapter.get_or_create_user"

import uuid
import logging

from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)

from . import settings as lt


def _provision_starter_memberships(user, invite):
    """Idempotently add `user` to configured starter Taiga projects with a
    low-privilege role. Best-effort: failures are logged and swallowed so they
    can never block or break SSO login."""
    from taiga.projects.models import Membership, Project

    if lt.get("LINKEDTRUST_PROVISION_REQUIRE_INVITE") and not invite:
        return
    slugs = lt.get("LINKEDTRUST_STARTER_PROJECT_SLUGS") or []
    if not slugs:
        return

    role_map = lt.get("LINKEDTRUST_ROLE_MAP") or {}
    invite_role = (invite or {}).get("r")
    role_name = (role_map.get(invite_role) if invite_role else None) \
        or lt.get("LINKEDTRUST_MEMBER_ROLE_NAME") or "stakeholder"

    for slug in slugs:
        try:
            with transaction.atomic():
                project = Project.objects.get(slug=slug)
                role = (project.roles.filter(slug=role_name).first()
                        or project.roles.filter(name__iexact=role_name).first())
                if role is None:
                    logger.warning("linkedtrust provision: role %r not in project %r", role_name, slug)
                    continue
                _, created = Membership.objects.get_or_create(
                    user=user, project=project,
                    defaults={"role": role, "is_admin": False, "email": user.email},
                )
                if created:
                    logger.info("linkedtrust provision: added %s to %r as %s", user.email, slug, role.slug)
        except Project.DoesNotExist:
            logger.warning("linkedtrust provision: starter project %r not found", slug)
        except Exception:
            logger.exception("linkedtrust provision: failed for project %r", slug)


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

    try:
        _provision_starter_memberships(user, userinfo.get("invite"))
    except Exception:
        logger.exception("linkedtrust provision: unexpected error for %s", email)

    tokens = make_auth_response_data(user)
    return user, tokens
