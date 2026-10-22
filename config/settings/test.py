"""Settings for the automated test suite: fast, isolated, no external services."""

import os

import dj_database_url

from .base import *  # noqa: F403
from .base import BASE_DIR

DEBUG = False
SECRET_KEY = "test-only-secret-key"  # noqa: S105
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

if os.environ.get("TEST_DATABASE") == "postgres":
    # CI runs the suite against PostgreSQL to verify production compatibility.
    DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"])}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "test-db.sqlite3",
            "TEST": {"NAME": None},
        }
    }

# Fast hashing for tests only; production keeps Django's default PBKDF2 hasher.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CELERY_BROKER_URL = "memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

AI_PROVIDER = ""
AI_API_KEY = ""
CODE_RUNNER_URL = ""
BILLING_PROVIDER = ""
STRIPE_SECRET_KEY = ""
STRIPE_WEBHOOK_SECRET = ""
SITE_URL = "http://testserver"
# Deterministic recommendations in tests (no exploration, always the top-scored pick).
SKILLFORGE_ENGINE = {**SKILLFORGE_ENGINE, "EXPLORATION_RATE": 0.0, "TOP_K": 1}
LOGGING["root"]["level"] = "WARNING"
