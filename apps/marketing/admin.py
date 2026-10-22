from django.contrib import admin

from .models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ["email", "topic", "created_at", "handled"]
    list_filter = ["topic", "handled"]
    search_fields = ["email", "name", "message"]
