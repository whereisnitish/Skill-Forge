"""Local development settings. Never use in production."""

from .base import *  # noqa: F403
from .base import env, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

# The development billing adapter is only honoured when DEBUG is on.
BILLING_PROVIDER = env("BILLING_PROVIDER", "dev")
