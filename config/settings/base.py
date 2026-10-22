"""Base settings shared by every environment.

Environment-specific modules (dev, test, prod) import from here and override
only what differs. Every secret or deployment-specific value is read from the
environment; nothing sensitive is committed.
"""

from __future__ import annotations

from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

from config.env import env, env_bool, env_float, env_int, env_list, load_dotenv, normalise_smtp_password

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])

SITE_NAME = "SkillForge"
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")
SUPPORT_EMAIL = env("SUPPORT_EMAIL", "support@skillforge.local")
ADMIN_URL = env("DJANGO_ADMIN_URL", "admin/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sitemaps",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.marketing",
    "apps.catalog",
    "apps.learning",
    "apps.onboarding",
    "apps.mentor",
    "apps.notifications",
    "apps.billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.core.middleware.UserTimezoneMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=env_int("DATABASE_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "learning:today"
LOGOUT_REDIRECT_URL = "marketing:home"
PASSWORD_RESET_TIMEOUT = 60 * 60 * 3  # 3 hours
EMAIL_VERIFICATION_TIMEOUT = 60 * 60 * 24 * 3  # 3 days

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# ---------------------------------------------------------------------------
# Cache & Redis
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "sf",
            "TIMEOUT": 300,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "skillforge-local",
        }
    }

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL or "memory://")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not REDIS_URL)
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 120
CELERY_TASK_SOFT_TIME_LIMIT = 100
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_BEAT_SCHEDULE = {
    "prepare-daily-sessions": {
        "task": "apps.learning.tasks.prepare_daily_sessions",
        "schedule": crontab(minute=5),
    },
    "send-daily-reminders": {
        "task": "apps.notifications.tasks.send_daily_reminders",
        "schedule": crontab(minute=0),
    },
    "send-review-reminders": {
        "task": "apps.notifications.tasks.send_review_reminders",
        "schedule": crontab(minute=30),
    },
    "retry-pending-evaluations": {
        "task": "apps.learning.tasks.retry_pending_evaluations",
        "schedule": crontab(minute="*/10"),
    },
    "expire-subscriptions": {
        "task": "apps.billing.tasks.expire_lapsed_subscriptions",
        "schedule": crontab(hour=3, minute=15),
    },
    "daily-cleanup": {
        "task": "apps.core.tasks.cleanup_stale_data",
        "schedule": crontab(hour=4, minute=0),
    },
}

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
# Either Django's EMAIL_* names or the NOTIFICATION_BACKEND / SMTP_* names may be
# used; EMAIL_* wins when both are set.
EMAIL_BACKENDS = {
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
    "console": "django.core.mail.backends.console.EmailBackend",
    "locmem": "django.core.mail.backends.locmem.EmailBackend",
}
_notification_backend = env("NOTIFICATION_BACKEND", "console").strip().lower()
if _notification_backend not in EMAIL_BACKENDS:
    raise ImproperlyConfigured(f"NOTIFICATION_BACKEND must be one of {sorted(EMAIL_BACKENDS)}.")
EMAIL_BACKEND = env("EMAIL_BACKEND", EMAIL_BACKENDS[_notification_backend])
EMAIL_HOST = env("EMAIL_HOST", env("SMTP_HOST", ""))
EMAIL_PORT = env_int("EMAIL_PORT", env_int("SMTP_PORT", 587))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", env("SMTP_USERNAME", ""))
EMAIL_HOST_PASSWORD = normalise_smtp_password(
    env("EMAIL_HOST_PASSWORD", env("SMTP_PASSWORD", env("SMTP_PASSWORD_VAULT_REF", "")))
)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465)  # implicit TLS on 465, STARTTLS otherwise
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", not EMAIL_USE_SSL)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 15)
_smtp_from = env("SMTP_FROM", "")
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", f"SkillForge <{_smtp_from}>" if _smtp_from else "SkillForge <no-reply@skillforge.local>"
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ---------------------------------------------------------------------------
# Security (tightened further in prod.py)
# ---------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)
RATELIMIT_ENABLED = env_bool("RATELIMIT_ENABLED", True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", "INFO")
LOG_FORMAT = env("LOG_FORMAT", "text")  # "text" or "json"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.logging.RequestIDFilter"}},
    "formatters": {
        "text": {
            "format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
        },
        "json": {"()": "apps.core.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT if LOG_FORMAT in {"text", "json"} else "text",
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "django.security": {"level": "WARNING"},
        "celery": {"level": "INFO"},
        "kombu": {"level": "ERROR"},
        "httpx": {"level": "WARNING"},
    },
}

# ---------------------------------------------------------------------------
# SkillForge: adaptive engine
# ---------------------------------------------------------------------------
SKILLFORGE_ENGINE = {
    # Initial, configurable heuristic. Not a scientifically validated formula.
    "SELECTION_WEIGHTS": {
        "weakness": env_float("ENGINE_WEIGHT_WEAKNESS", 0.35),
        "review_urgency": env_float("ENGINE_WEIGHT_REVIEW", 0.25),
        "goal_relevance": env_float("ENGINE_WEIGHT_GOAL", 0.20),
        "dependency_importance": env_float("ENGINE_WEIGHT_DEPENDENCY", 0.20),
    },
    "EXPLORATION_RATE": env_float("ENGINE_EXPLORATION_RATE", 0.15),
    "TOP_K": env_int("ENGINE_TOP_K", 3),
    "MAX_DAILY_RECOMMENDATIONS": env_int("ENGINE_MAX_DAILY_RECOMMENDATIONS", 6),
}

# ---------------------------------------------------------------------------
# SkillForge: AI mentor (optional)
# ---------------------------------------------------------------------------
AI_PROVIDER = env("AI_PROVIDER", "")  # "anthropic" or empty for curated fallback
AI_MODEL = env("AI_MODEL", "claude-opus-5-5")
AI_API_KEY = env("AI_API_KEY", "")
AI_TIMEOUT_SECONDS = env_float("AI_TIMEOUT_SECONDS", 45.0)
# Thinking tokens count toward this cap on current models, so keep headroom.
AI_MAX_OUTPUT_TOKENS = env_int("AI_MAX_OUTPUT_TOKENS", 4000)
AI_EFFORT = env("AI_EFFORT", "medium")  # low | medium | high
AI_USE_SERVER_FALLBACKS = env_bool("AI_USE_SERVER_FALLBACKS", True)
AI_REQUESTS_PER_MINUTE = env_int("AI_REQUESTS_PER_MINUTE", 6)

# ---------------------------------------------------------------------------
# SkillForge: sandboxed code runner (optional, separate service)
# ---------------------------------------------------------------------------
CODE_RUNNER_URL = env("CODE_RUNNER_URL", "").rstrip("/")
CODE_RUNNER_TOKEN = env("CODE_RUNNER_TOKEN", "")
CODE_RUNNER_TIMEOUT_SECONDS = env_float("CODE_RUNNER_TIMEOUT_SECONDS", 20.0)
CODE_RUNNER_MAX_CONCURRENT_PER_USER = env_int("CODE_RUNNER_MAX_CONCURRENT_PER_USER", 1)

# ---------------------------------------------------------------------------
# SkillForge: billing
# ---------------------------------------------------------------------------
BILLING_PROVIDER = env("BILLING_PROVIDER", "")  # "stripe", "dev" (DEBUG only) or empty
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_IDS = {
    "pro": env("STRIPE_PRICE_PRO", ""),
    "interview": env("STRIPE_PRICE_INTERVIEW", ""),
}
