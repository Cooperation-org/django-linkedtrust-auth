"""Per-flow ?next= return origins: validation, session carry, callback targets.

Run from the repo root with the venv python:
    python tests/test_next_origin.py
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
from django.conf import settings

settings.configure(
    SECRET_KEY="test-only",
    ALLOWED_HOSTS=["*"],
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django.contrib.sessions",
    ],
    LINKEDTRUST_URL="https://idp.example.com",
    LINKEDTRUST_CLIENT_ID="test-client",
    LINKEDTRUST_FRONTEND_URL="https://marten.workers.vc",
    LINKEDTRUST_FRONTEND_URLS="https://chiku.workers.vc",
    DATABASES={},
)
django.setup()

from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory

from linkedtrust_auth import views
from linkedtrust_auth.views import CallbackView, RedirectView, resolve_next_origin


def make_request(path, get_params=None):
    factory = RequestFactory()
    request = factory.get(path, data=get_params or {}, HTTP_HOST="taiga.workers.vc")
    SessionMiddleware(lambda r: None).process_request(request)
    # RequestFactory skips URL resolving; the redirect view only needs the route.
    request.resolver_match = SimpleNamespace(route="api/v1/auth/linkedtrust/redirect")
    return request


class ResolveNextOriginTests(unittest.TestCase):
    def test_allowlisted_origin_passes(self):
        self.assertEqual(
            resolve_next_origin("https://chiku.workers.vc/oauth/callback"),
            "https://chiku.workers.vc",
        )

    def test_default_frontend_is_always_allowed(self):
        self.assertEqual(
            resolve_next_origin("https://marten.workers.vc/oauth/callback"),
            "https://marten.workers.vc",
        )

    def test_only_the_origin_is_honored(self):
        self.assertEqual(
            resolve_next_origin("https://chiku.workers.vc/elsewhere?x=1#frag"),
            "https://chiku.workers.vc",
        )

    def test_unknown_origin_rejected(self):
        self.assertIsNone(resolve_next_origin("https://evil.example.com/oauth/callback"))

    def test_suffix_trick_rejected(self):
        self.assertIsNone(resolve_next_origin("https://chiku.workers.vc.evil.com/"))

    def test_non_urls_rejected(self):
        for raw in (None, "", "not a url", "javascript:alert(1)", "//chiku.workers.vc/x", "/oauth/callback"):
            self.assertIsNone(resolve_next_origin(raw), raw)


class RedirectViewTests(unittest.TestCase):
    def test_valid_next_is_carried_in_session(self):
        request = make_request(
            "/api/v1/auth/linkedtrust/redirect",
            {"next": "https://chiku.workers.vc/oauth/callback"},
        )
        response = RedirectView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("oauth/authorize", response["Location"])
        self.assertEqual(
            request.session[views.NEXT_SESSION_KEY], "https://chiku.workers.vc"
        )

    def test_evil_next_is_dropped_from_session(self):
        request = make_request(
            "/api/v1/auth/linkedtrust/redirect",
            {"next": "https://evil.example.com/oauth/callback"},
        )
        response = RedirectView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(views.NEXT_SESSION_KEY, request.session)

    def test_no_next_leaves_no_session_key(self):
        request = make_request("/api/v1/auth/linkedtrust/redirect")
        RedirectView.as_view()(request)
        self.assertNotIn(views.NEXT_SESSION_KEY, request.session)


class CallbackTargetTests(unittest.TestCase):
    def _callback_request_with_session(self, session_values):
        factory = RequestFactory()
        request = factory.get("/api/v1/auth/linkedtrust/callback", HTTP_HOST="taiga.workers.vc")
        SessionMiddleware(lambda r: None).process_request(request)
        for key, value in session_values.items():
            request.session[key] = value
        return request

    def test_success_defaults_to_marten(self):
        request = self._callback_request_with_session({})
        response = CallbackView()._success(request, {"auth_token": "abc"})
        self.assertEqual(
            response["Location"], "https://marten.workers.vc/oauth/callback#auth_token=abc"
        )

    def test_success_honors_carried_next(self):
        request = self._callback_request_with_session(
            {views.NEXT_SESSION_KEY: "https://chiku.workers.vc"}
        )
        response = CallbackView()._success(request, {"auth_token": "abc"})
        self.assertEqual(
            response["Location"], "https://chiku.workers.vc/oauth/callback#auth_token=abc"
        )
        # Single-use: the key is consumed.
        self.assertNotIn(views.NEXT_SESSION_KEY, request.session)

    def test_success_ignores_session_origin_off_allowlist(self):
        request = self._callback_request_with_session(
            {views.NEXT_SESSION_KEY: "https://evil.example.com"}
        )
        response = CallbackView()._success(request, {"auth_token": "abc"})
        self.assertTrue(
            response["Location"].startswith("https://marten.workers.vc/oauth/callback#")
        )

    def test_fail_follows_the_same_base(self):
        request = self._callback_request_with_session(
            {views.NEXT_SESSION_KEY: "https://chiku.workers.vc"}
        )
        response = CallbackView()._fail(request, "auth_failed")
        self.assertEqual(
            response["Location"], "https://chiku.workers.vc/login?error=auth_failed"
        )

        plain = self._callback_request_with_session({})
        response = CallbackView()._fail(plain, "auth_failed")
        self.assertEqual(
            response["Location"], "https://marten.workers.vc/login?error=auth_failed"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
