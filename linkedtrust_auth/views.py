# Generic Django views for LinkedTrust OIDC server-side flow.
#
# GET  /redirect  → 302 to IdP authorize endpoint
# GET  /callback  → exchanges code, calls get_or_create_user hook, redirects to frontend
#
# The consuming app provides a `get_or_create_user(userinfo) -> (user, tokens_dict)` hook
# via LINKEDTRUST_USER_HANDLER setting (dotted path) or by subclassing CallbackView.

import logging
import uuid
from urllib.parse import urlencode

from django.http import HttpResponseRedirect, HttpResponseBadRequest
from django.views import View

from . import settings as lt
from .oidc import authorize_url, exchange_code, get_userinfo, OIDCError

logger = logging.getLogger(__name__)

STATE_SESSION_KEY = "linkedtrust_oauth_state"
REDIRECT_URI_SESSION_KEY = "linkedtrust_redirect_uri"


class RedirectView(View):
    """GET /redirect — start the OIDC flow by redirecting browser to the IdP."""

    def get(self, request):
        state = uuid.uuid4().hex
        request.session[STATE_SESSION_KEY] = state

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
