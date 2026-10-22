from django.contrib import admin

from .models import MentorRequest


@admin.register(MentorRequest)
class MentorRequestAdmin(admin.ModelAdmin):
    list_display = ["user", "kind", "status", "source", "provider", "error_code", "latency_ms", "created_at"]
    list_filter = ["kind", "status", "source", "error_code"]
    search_fields = ["user__email"]
    readonly_fields = [f.name for f in MentorRequest._meta.fields]
