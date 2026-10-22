from django.contrib import admin

from .models import (
    AttemptEvaluation,
    LearningAttempt,
    LearningEvent,
    LearningGoal,
    LearningSession,
    MilestoneCompletion,
    Recommendation,
    ReviewRecord,
    ReviewSchedule,
    SkillEvidence,
    SkillMastery,
    UserAchievement,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Learning records are an audit trail: viewable by staff, never edited in the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LearningGoal)
class LearningGoalAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "goal_type", "path", "status", "is_primary", "daily_minutes", "updated_at"]
    list_filter = ["status", "goal_type", "is_primary"]
    search_fields = ["title", "user__email"]
    raw_id_fields = ["user", "path", "path_version"]
    filter_horizontal = ["focus_skills"]


@admin.register(LearningSession)
class LearningSessionAdmin(ReadOnlyAdmin):
    list_display = ["user", "local_date", "goal", "minutes_budget", "status"]
    list_filter = ["status"]
    search_fields = ["user__email"]


@admin.register(Recommendation)
class RecommendationAdmin(ReadOnlyAdmin):
    list_display = ["challenge", "user", "reason_code", "score", "status", "strategy_version", "created_at"]
    list_filter = ["status", "reason_code", "strategy_version"]
    search_fields = ["user__email", "challenge__slug", "reason_text"]


class EvaluationInline(admin.StackedInline):
    model = AttemptEvaluation
    can_delete = False
    extra = 0
    readonly_fields = [f.name for f in AttemptEvaluation._meta.fields]


@admin.register(LearningAttempt)
class LearningAttemptAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "challenge", "status", "is_review", "is_diagnostic", "submitted_at"]
    list_filter = ["status", "is_review", "is_diagnostic", "challenge__kind"]
    search_fields = ["user__email", "challenge__slug"]
    inlines = [EvaluationInline]


@admin.register(SkillMastery)
class SkillMasteryAdmin(ReadOnlyAdmin):
    list_display = ["user", "skill", "mean_at_update", "evidence_count", "last_practiced_at", "model_version"]
    search_fields = ["user__email", "skill__name"]


@admin.register(SkillEvidence)
class SkillEvidenceAdmin(ReadOnlyAdmin):
    list_display = ["user", "skill", "score", "weight", "mastery_before", "mastery_after", "created_at"]
    search_fields = ["user__email", "skill__name"]


@admin.register(ReviewSchedule)
class ReviewScheduleAdmin(ReadOnlyAdmin):
    list_display = ["user", "skill", "due_at", "interval_days", "ease", "repetitions", "lapses"]
    search_fields = ["user__email", "skill__name"]


@admin.register(ReviewRecord)
class ReviewRecordAdmin(ReadOnlyAdmin):
    list_display = ["schedule", "outcome", "quality", "new_interval_days", "reviewed_at"]
    list_filter = ["outcome"]


@admin.register(LearningEvent)
class LearningEventAdmin(ReadOnlyAdmin):
    list_display = ["event_type", "user", "occurred_at"]
    list_filter = ["event_type"]
    search_fields = ["user__email"]


@admin.register(UserAchievement)
class UserAchievementAdmin(ReadOnlyAdmin):
    list_display = ["user", "code", "earned_at"]
    list_filter = ["code"]


@admin.register(MilestoneCompletion)
class MilestoneCompletionAdmin(ReadOnlyAdmin):
    list_display = ["user", "goal", "milestone", "completed_at"]
