from django.contrib import admin

from .models import TaskFailure


@admin.register(TaskFailure)
class TaskFailureAdmin(admin.ModelAdmin):
    list_display = ["task_name", "exception_type", "task_id", "occurred_at", "resolved"]
    list_filter = ["resolved", "task_name", "exception_type"]
    search_fields = ["task_name", "task_id", "message"]
    readonly_fields = ["task_name", "task_id", "exception_type", "message", "occurred_at"]
