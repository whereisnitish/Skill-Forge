"""Production settings. All secrets must come from the environment."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import BILLING_PROVIDER, env, env_bool, env_int

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)
if len(SECRET_KEY) < 40 or SECRET_KEY.startswith("dev-only"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a long, random production secret.")

if BILLING_PROVIDER == "dev":
    raise ImproperlyConfigured("The development billing adapter cannot be used in production.")

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SECURE_REDIRECT_EXEMPT = [r"^healthz/$", r"^readyz/$"]
SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_NAME = "__Host-sessionid"
CSRF_COOKIE_NAME = "__Host-csrftoken"

LOG_FORMAT = env("LOG_FORMAT", "json")
LOGGING["handlers"]["console"]["formatter"] = LOG_FORMAT
