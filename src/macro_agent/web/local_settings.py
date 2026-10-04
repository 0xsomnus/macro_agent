"""Explicit loopback-only development overrides; do not use for deployment."""

import os

# A throwaway development key never becomes the production settings fallback.
os.environ.setdefault("MACRO_SECRET_KEY", "synthetic-local-only-key-with-no-deployment-authority-2026")
from .settings import *  # noqa: F403

DATABASES["default"]["NAME"] = os.environ.get("MACRO_DB_NAME", "macro_agent_dev")
if DATABASES["default"]["HOST"] not in ("127.0.0.1", "localhost", "::1"):
    raise ImproperlyConfigured("Local settings require a loopback PostgreSQL host")

ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
MACRO_ALLOW_SYNTHETIC_SETUP = os.environ.get("MACRO_ALLOW_SYNTHETIC_SETUP") == "1"
if MACRO_ALLOW_SYNTHETIC_SETUP and not (
        DATABASES["default"]["NAME"].endswith("_dev") or
        DATABASES["default"]["NAME"].startswith("test_")):
    raise ImproperlyConfigured("Synthetic setup requires an explicitly named development/test database")
