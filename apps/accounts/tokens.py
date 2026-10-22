"""Email verification tokens.

Reuses Django's HMAC-signed token format. The hash covers the user's id, email
and verification state, so a token stops working once the address is verified
or changed; the timestamp limits it to EMAIL_VERIFICATION_TIMEOUT seconds.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "apps.accounts.tokens.EmailVerificationTokenGenerator"

    def _make_hash_value(self, user, timestamp: int) -> str:
        verified = user.email_verified_at.isoformat() if user.email_verified_at else ""
        return f"{user.pk}{user.email}{verified}{timestamp}"

    def check_token(self, user, token) -> bool:
        if not (user and token):
            return False
        try:
            ts_b36, _ = token.split("-")
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False
        valid = any(
            constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token)
            for secret in [self.secret, *self.secret_fallbacks]
        )
        if not valid:
            return False
        return (self._num_seconds(self._now()) - ts) <= settings.EMAIL_VERIFICATION_TIMEOUT


email_verification_token = EmailVerificationTokenGenerator()
