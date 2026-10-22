import copy

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from apps.catalog.content_loader import load_content, validate
from apps.catalog.models import Challenge, ChallengeVersion, LearningPath, Skill, SkillPrerequisite
from apps.catalog.seeding import sync_catalog
from apps.learning.services import attempts as attempt_service
from tests.factories import small_bundle
from tests.learning.helpers import correct_answer


def test_curated_content_is_valid():
    bundle = load_content()
    report = validate(bundle)
    assert report.ok, report.errors
    assert len(bundle.skills) >= 40 and len(bundle.challenges) >= 120
    kinds = {c["kind"] for c in bundle.challenges}
    assert kinds == {
        "multiple_choice",
        "short_answer",
        "python_code",
        "debugging",
        "concept_explanation",
        "code_review",
    }
    for skill in bundle.skills:
        assert any(c["skill"] == skill["slug"] and c.get("diagnostic") for c in bundle.challenges), skill["slug"]


def test_validator_catches_cycles_and_bad_references():
    bundle = small_bundle()
    bundle.skills[0]["prerequisites"] = ["advanced"]  # basics -> advanced -> intermediate -> basics
    bundle.challenges[0]["skill"] = "missing-skill"
    errors = " ".join(validate(bundle).errors)
    assert "cycle" in errors.lower()
    assert "unknown skill 'missing-skill'" in errors


def test_rubric_model_answers_pass_their_own_rubrics():
    """Each curated rubric challenge's model answer must earn a pass from the real grader."""
    from apps.evaluation.base import ChallengeSpec
    from apps.evaluation.rubric import RubricEvaluator

    evaluator = RubricEvaluator()
    failures = []
    for c in load_content().challenges:
        if c["kind"] not in {"concept_explanation", "code_review"} or not c.get("solution"):
            continue
        spec = ChallengeSpec(c["kind"], c["content"], reference_text=c["prompt"] + "\n" + c["content"].get("code", ""))
        if not evaluator.evaluate(spec, {"text": c["solution"]}).passed:
            failures.append(c["slug"])
    assert not failures, failures


@pytest.mark.django_db
def test_seeding_is_idempotent_and_versions_changes():
    sync_catalog(small_bundle())
    counts = (
        Skill.objects.count(),
        Challenge.objects.count(),
        ChallengeVersion.objects.count(),
        SkillPrerequisite.objects.count(),
    )
    stats = sync_catalog(small_bundle())
    assert stats["challenges_unchanged"] == Challenge.objects.count()
    assert (
        Skill.objects.count(),
        Challenge.objects.count(),
        ChallengeVersion.objects.count(),
        SkillPrerequisite.objects.count(),
    ) == counts

    changed = small_bundle()
    changed.challenges[0] = copy.deepcopy(changed.challenges[0])
    changed.challenges[0]["prompt"] = "A reworded prompt."
    changed.challenges = [c for c in changed.challenges if c["slug"] != "other-short"]
    stats = sync_catalog(changed)
    challenge = Challenge.objects.get(slug="basics-mcq")
    assert challenge.versions.count() == 2 and challenge.current_version.number == 2
    assert stats["challenges_deactivated"] == 1
    assert not Challenge.objects.get(slug="other-short").is_active
    assert LearningPath.objects.filter(is_default_for_goal=True, goal_type="python").count() == 1


@pytest.mark.django_db
def test_full_catalogue_seed_command():
    call_command("seed_catalog", verbosity=0)
    assert Challenge.objects.published().count() >= 120
    call_command("check_skill_graph", verbosity=0)


@pytest.mark.django_db
def test_attempted_versions_are_immutable(learner):
    version = Challenge.objects.get(slug="basics-mcq").current_version
    attempt_service.submit_attempt(learner, version, correct_answer("basics-mcq"))
    version.title = "Changed after the fact"
    with pytest.raises(ValidationError):
        version.save()


@pytest.mark.django_db
def test_prerequisite_clean_rejects_cycles(catalog):
    basics = Skill.objects.get(slug="basics")
    advanced = Skill.objects.get(slug="advanced")
    link = SkillPrerequisite(skill=basics, prerequisite=advanced)
    with pytest.raises(ValidationError):
        link.clean()
    with pytest.raises(ValidationError):
        SkillPrerequisite(skill=basics, prerequisite=basics).clean()


def test_reference_solutions_pass_and_starters_fail():
    """Authoring check over trusted repository content (never learner code)."""
    from apps.catalog.verify_solutions import main

    assert main() == 0
