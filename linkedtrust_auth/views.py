# Generic Django views for LinkedTrust OIDC server-side flow.
#
# GET  /redirect  → 302 to IdP authorize endpoint
# GET  /callback  → exchanges code, calls get_or_create_user hook, redirects to frontend
#
# The consuming app provides a `get_or_create_user(userinfo) -> (user, tokens_dict)` hook
# via LINKEDTRUST_USER_HANDLER setting (dotted path) or by subclassing CallbackView.

import logging
import time
import uuid
from urllib.parse import urlencode

from django.http import HttpResponseRedirect, HttpResponseBadRequest
from django.views import View

from . import settings as lt
from . import invites
from .oidc import authorize_url, exchange_code, get_userinfo, OIDCError

logger = logging.getLogger(__name__)

STATE_SESSION_KEY = "linkedtrust_oauth_state"
REDIRECT_URI_SESSION_KEY = "linkedtrust_redirect_uri"
INVITE_SESSION_KEY = "linkedtrust_invite_token"


class RedirectView(View):
    """GET /redirect — start the OIDC flow by redirecting browser to the IdP."""

    def get(self, request):
        state = uuid.uuid4().hex
        request.session[STATE_SESSION_KEY] = state

        # Carry an invite token (if any) through the OIDC round-trip in the session.
        invite_token = request.GET.get("invite")
        if invite_token:
            request.session[INVITE_SESSION_KEY] = invite_token
        else:
            request.session.pop(INVITE_SESSION_KEY, None)

        # Build the callback URL pointing back to this Django app
        callback_path = request.resolver_match.route.rsplit("redirect", 1)[0] + "callback"
        callback_url = request.build_absolute_uri(f"/{callback_path}")
        request.session[REDIRECT_URI_SESSION_KEY] = callback_url

        try:
            url = authorize_url(callback_url, state)
        except OIDCError as e:
            return HttpResponseBadRequest(str(e))

        return HttpResponseRedirect(url)


class CallbackView(View):
    """GET /callback — IdP redirects here with ?code=&state=. Exchange and redirect to frontend."""

    def get_or_create_user(self, userinfo):
        """
        Override this in subclasses or set LINKEDTRUST_USER_HANDLER.
        Must return (user, tokens_dict) where tokens_dict has at least 'auth_token'.
        """
        handler_path = lt.get("LINKEDTRUST_USER_HANDLER")
        if handler_path:
            from django.utils.module_loading import import_string
            handler = import_string(handler_path)
            return handler(userinfo)
        raise NotImplementedError("Set LINKEDTRUST_USER_HANDLER or subclass CallbackView")

    def get(self, request):
        error = request.GET.get("error")
        if error:
            return self._fail(request, "auth_failed")

        state = request.GET.get("state")
        expected_state = request.session.pop(STATE_SESSION_KEY, None)
        if not state or not expected_state or state != expected_state:
            return self._fail(request, "state_mismatch")

        code = request.GET.get("code")
        if not code:
            return self._fail(request, "auth_failed")

        redirect_uri = request.session.pop(REDIRECT_URI_SESSION_KEY, None)
        if not redirect_uri:
            redirect_uri = request.build_absolute_uri(request.path)

        try:
            token_data = exchange_code(code, redirect_uri)
            access_token = token_data.get("access_token")
            if not access_token:
                return self._fail(request, "auth_failed")

            userinfo = get_userinfo(access_token)

            # Resolve the invite (if the flow carried one) and enforce policy.
            invite_token = request.session.pop(INVITE_SESSION_KEY, None)
            invite_payload = None
            if invite_token:
                try:
                    invite_payload = invites.verify(
                        invite_token,
                        now=time.time(),
                        app_slug=lt.get("LINKEDTRUST_APP_SLUG") or None,
                        email=userinfo.get("email"),
                    )
                except invites.InviteError as e:
                    logger.warning("LinkedTrust invite rejected: %s", e)
                    return self._fail(request, "invite_invalid")

            if lt.get("LINKEDTRUST_REQUIRE_INVITE") and not invite_payload:
                logger.warning("LinkedTrust login blocked: invite required, none valid")
                return self._fail(request, "invite_required")

            # Hand the invite to the user handler under a stable key so adapters
            # can honor role/apps without a signature change.
            userinfo["invite"] = invite_payload
            user, tokens = self.get_or_create_user(userinfo)
        except OIDCError as e:
            logger.error("LinkedTrust callback error: %s", e)
            return self._fail(request, "auth_failed")
        except Exception as e:
            logger.exception("LinkedTrust callback unexpected error: %s", e)
            return self._fail(request, "auth_failed")

        return self._success(request, tokens)

    def _frontend_url(self):
        return lt.get("LINKEDTRUST_FRONTEND_URL").rstrip("/")

    def _success(self, request, tokens):
        """Redirect to frontend with tokens in URL fragment (not query — keeps them out of logs)."""
        frontend = self._frontend_url()
        callback_path = lt.get("LINKEDTRUST_FRONTEND_CALLBACK")
        fragment = urlencode(tokens)
        return HttpResponseRedirect(f"{frontend}{callback_path}#{fragment}")

    def _fail(self, request, error_code):
        frontend = self._frontend_url()
        return HttpResponseRedirect(f"{frontend}/login?error={error_code}")


class InviteDashboardView(View):
    """Tiny admin-gated page to mint invite links. GET shows the form; POST mints.

    Gated to staff/superusers. No database — the token IS the invite.
    Mount at e.g. /api/v1/auth/linkedtrust/invites/ .
    """

    def _forbidden(self):
        from django.http import HttpResponse
        return HttpResponse("Forbidden — admin only.", status=403)

    def _allowed(self, request):
        u = getattr(request, "user", None)
        return bool(u and u.is_authenticated and (getattr(u, "is_superuser", False) or getattr(u, "is_staff", False)))

    def get(self, request):
        if not self._allowed(request):
            return self._forbidden()
        return self._render(request, link="")

    def post(self, request):
        if not self._allowed(request):
            return self._forbidden()
        email = request.POST.get("email", "")
        role = request.POST.get("role", "")
        apps = [s.strip() for s in request.POST.get("apps", "").split(",") if s.strip()]
        try:
            days = int(request.POST.get("days", "14"))
        except ValueError:
            days = 14
        token = invites.mint(email=email, role=role, apps=apps,
                             ttl_seconds=days * 86400, now=time.time(),
                             jti=uuid.uuid4().hex[:8])
        base = request.build_absolute_uri("/").rstrip("/")
        link = f"{base}/api/v1/auth/linkedtrust/redirect?invite={token}"
        return self._render(request, link=link)

    def _render(self, request, link):
        from django.http import HttpResponse
        from django.utils.html import escape
        from django.middleware.csrf import get_token
        csrf = get_token(request)
        result = ""
        if link:
            result = (
                '<p><b>Invite link (send this to the volunteer — works at every app '
                'sharing the invite secret):</b></p>'
                f'<textarea rows="4" style="width:100%" readonly '
                f'onclick="this.select()">{escape(link)}</textarea>'
            )
        html = f"""<!doctype html><meta charset="utf-8">
<title>LinkedTrust invites</title>
<body style="font-family:system-ui;max-width:640px;margin:2rem auto;padding:0 1rem">
<h2>Mint a volunteer invite</h2>
<form method="post">
  <input type="hidden" name="csrfmiddlewaretoken" value="{csrf}">
  <label>Email (optional, binds the invite to one person)<br>
    <input name="email" style="width:100%" placeholder="jane@example.org"></label><br><br>
  <label>Role<br><input name="role" style="width:100%" value="volunteer"></label><br><br>
  <label>Apps (comma-separated slugs, blank = all)<br>
    <input name="apps" style="width:100%" placeholder="marten,cases"></label><br><br>
  <label>Expires in (days)<br><input name="days" style="width:100%" value="14"></label><br><br>
  <button type="submit">Generate link</button>
</form>
{result}
</body>"""
        return HttpResponse(html)
