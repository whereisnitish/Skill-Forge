from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, User


@receiver(post_save, sender=User)
def ensure_profile(sender, instance: User, created: bool, **kwargs) -> None:
    """Every account has exactly one profile, however the user was created."""
    if created:
        Profile.objects.get_or_create(user=instance)
