# Mint an invite link from the command line.
#
#   python manage.py lt_mint_invite --email jane@example.org --role volunteer \
#       --apps marten,cases --base https://help.raisethevoices.org --days 14
#
# Prints the full invite URL. The SAME token also works at any other app that
# shares LINKEDTRUST_INVITE_SECRET (e.g. cases), so one link covers both.

import time
import uuid

from django.core.management.base import BaseCommand, CommandError

from ... import invites
from ... import settings as lt


class Command(BaseCommand):
    help = "Mint a LinkedTrust invite token / link for a volunteer."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="", help="Bind the invite to this email (optional)")
        parser.add_argument("--role", default="", help="Role to grant (default: LINKEDTRUST_DEFAULT_ROLE)")
        parser.add_argument("--apps", default="", help="Comma-separated app slugs the invite is valid for (default: all)")
        parser.add_argument("--days", type=int, default=14, help="Days until the invite expires")
        parser.add_argument(
            "--base", default="",
            help="Backend base URL to build the link (e.g. https://help.raisethevoices.org). "
                 "If omitted, only the raw token is printed.",
        )

    def handle(self, *args, **opts):
        if not lt.get("LINKEDTRUST_INVITE_SECRET"):
            raise CommandError("LINKEDTRUST_INVITE_SECRET is not set in settings.")

        apps = [s.strip() for s in opts["apps"].split(",") if s.strip()]
        token = invites.mint(
            email=opts["email"],
            role=opts["role"],
            apps=apps,
            ttl_seconds=opts["days"] * 86400,
            now=time.time(),
            jti=uuid.uuid4().hex[:8],
        )

        self.stdout.write(self.style.SUCCESS("Invite token:"))
        self.stdout.write(token)
        base = opts["base"].rstrip("/")
        if base:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Invite link:"))
            self.stdout.write(f"{base}/api/v1/auth/linkedtrust/redirect?invite={token}")
