"""Account workflows. Views call these; they own transactions and side effects."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .models import User

logger = logging.getLogger(__name__)


def queue_verification_email(user: User, *, reason: str = "signup") -> None:
    """Send the welcome/verify email ("signup") or the confirm-new-address email ("change")."""
    from .tasks import send_verification_email

    transaction.on_commit(lambda: send_verification_email.delay(user.pk, reason))


@transaction.atomic
def register_user(*, email: str, password: str, display_name: str = "", tz: str = "UTC") -> User:
    user = User.objects.create_user(email=email, password=password, display_name=display_name)
    profile = user.profile
    profile.timezone = tz
    profile.save(update_fields=["timezone", "updated_at"])
    queue_verification_email(user)
    logger.info("account.registered", extra={"user_id": user.pk})
    return user


def mark_email_verified(user: User) -> bool:
    if user.is_email_verified:
        return False
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    logger.info("account.email_verified", extra={"user_id": user.pk})
    return True


@transaction.atomic
def change_email(user: User, new_email: str) -> None:
    user.email = new_email.lower()
    user.email_verified_at = None
    user.save(update_fields=["email", "email_verified_at"])
    queue_verification_email(user, reason="change")


def delete_account(user: User) -> None:
    """Permanently delete the account and all learning data owned by it.

    Paid subscriptions are cancelled with the provider first (best effort); a
    provider failure is logged and does not block the user's right to delete.
    """
    from apps.billing.services import cancel_subscription_for_deletion

    cancel_subscription_for_deletion(user)
    user_id = user.pk
    with transaction.atomic():
        user.delete()
    logger.info("account.deleted", extra={"user_id": user_id})
