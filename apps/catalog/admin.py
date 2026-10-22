from django.contrib import admin

from .models import (
    Challenge,
    ChallengeTestCase,
    ChallengeVersion,
    LearningPath,
    LearningPathVersion,
    PathMilestone,
    PathStep,
    Skill,
    SkillCategory,
    SkillPrerequisite,
)


@admin.register(SkillCategory)
class SkillCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "domain", "order"]
    prepopulated_fields = {"slug": ["name"]}


class PrerequisiteInline(admin.TabularInline):
    model = SkillPrerequisite
    fk_name = "skill"
    extra = 0
    autocomplete_fields = ["prerequisite"]


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "difficulty", "is_active"]
    list_filter = ["category", "difficulty", "is_active"]
    search_fields = ["name", "slug", "summary"]
    inlines = [PrerequisiteInline]
    filter_horizontal = ["related_skills"]


class TestCaseInline(admin.TabularInline):
    model = ChallengeTestCase
    extra = 0


@admin.register(ChallengeVersion)
class ChallengeVersionAdmin(admin.ModelAdmin):
    list_display = ["challenge", "number", "title", "evaluation_version", "created_at"]
    search_fields = ["challenge__slug", "title"]
    inlines = [TestCaseInline]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.attempts.exists():
            return [f.name for f in ChallengeVersion._meta.fields]
        return ["content_hash", "created_at"]


@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ["slug", "skill", "kind", "difficulty", "source", "review_status", "is_active"]
    list_filter = ["kind", "difficulty", "source", "review_status", "is_active", "skill__category"]
    search_fields = ["slug", "skill__name"]
    autocomplete_fields = ["skill", "secondary_skills"]
    readonly_fields = ["current_version"]


class StepInline(admin.TabularInline):
    model = PathStep
    extra = 0


@admin.register(PathMilestone)
class PathMilestoneAdmin(admin.ModelAdmin):
    list_display = ["title", "version", "order"]
    inlines = [StepInline]


@admin.register(LearningPath)
class LearningPathAdmin(admin.ModelAdmin):
    list_display = ["name", "goal_type", "is_default_for_goal", "is_premium", "is_active"]
    list_filter = ["goal_type", "is_premium", "is_active"]


@admin.register(LearningPathVersion)
class LearningPathVersionAdmin(admin.ModelAdmin):
    list_display = ["path", "number", "published_at"]
