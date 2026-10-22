from django.contrib import admin

from .models import Subscription, UsageRecord, WebhookEvent


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "plan", "status", "provider", "current_period_end", "updated_at"]
    list_filter = ["plan", "status", "provider"]
    search_fields = ["user__email", "provider_customer_id", "provider_subscription_id"]


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ["user", "feature", "period", "count"]
    list_filter = ["feature"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["provider", "event_type", "event_id", "status", "received_at"]
    list_filter = ["provider", "status", "event_type"]
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]
