"""Explicit local development overrides; do not use for deployment."""

import os
from stat import S_IMODE

# A throwaway development key never becomes the production settings fallback.
os.environ.setdefault("MACRO_SECRET_KEY", "synthetic-local-only-key-with-no-deployment-authority-2026")
from .settings import *  # noqa: F403

DATABASES["default"]["NAME"] = os.environ.get("MACRO_DB_NAME", "macro_agent_dev")
if DATABASES["default"]["HOST"] not in ("127.0.0.1", "localhost", "::1"):
    # The native fallback has no TCP listener. Trust authentication is bounded
    # by this specific project-local socket directory and its private mode.
    socket_dir = BASE_DIR / ".local" / "pg-socket"
    if (DATABASES["default"]["HOST"] != str(socket_dir) or not socket_dir.is_dir()
            or socket_dir.is_symlink() or S_IMODE(socket_dir.stat().st_mode) != 0o700):
        raise ImproperlyConfigured("Local settings require loopback or the private project PostgreSQL socket")

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
