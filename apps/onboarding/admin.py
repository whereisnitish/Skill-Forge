from django.contrib import admin

from .models import OnboardingState


@admin.register(OnboardingState)
class OnboardingStateAdmin(admin.ModelAdmin):
    list_display = ["user", "step", "diagnostic_completed", "completed_at", "updated_at"]
    list_filter = ["step", "diagnostic_completed"]
    search_fields = ["user__email"]
    readonly_fields = ["data", "diagnostic_challenge_ids"]
