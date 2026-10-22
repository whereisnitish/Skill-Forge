from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "kind", "email_status", "created_at", "read_at"]
    list_filter = ["kind", "email_status"]
    search_fields = ["user__email", "title", "dedupe_key"]
    readonly_fields = [f.name for f in Notification._meta.fields]
