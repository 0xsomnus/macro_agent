"""Explicit PostgreSQL-only settings for the first Django foundation.

Production secrets and deployment are still an operational review. Local
fixtures require their own settings module and explicit synthetic setup gate.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[3]
SECRET_KEY = os.environ.get("MACRO_SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set MACRO_SECRET_KEY; there is no production fallback")

DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("MACRO_ALLOWED_HOSTS", "").split(",")
                 if host.strip()]
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "macro_agent.web.apps.WebConfig", "macro_agent.persistence.apps.PersistenceConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "macro_agent.web.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
AUTH_USER_MODEL = "macro_web.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Never silently replace PostgreSQL with SQLite when configuration is absent.
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("MACRO_DB_NAME", "macro_agent"),
    "USER": os.environ.get("MACRO_DB_USER", "macro_agent"),
    "PASSWORD": os.environ.get("MACRO_DB_PASSWORD", ""),
    "HOST": os.environ.get("MACRO_DB_HOST", "127.0.0.1"),
    "PORT": os.environ.get("MACRO_DB_PORT", "5432"),
    "CONN_MAX_AGE": 0,
    "OPTIONS": {"connect_timeout": 5},
    "TEST": {"NAME": os.environ.get("MACRO_TEST_DB_NAME", "test_macro_agent")},
}}
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / ".local" / "static"
MACRO_ALLOW_SYNTHETIC_SETUP = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = "DENY"
