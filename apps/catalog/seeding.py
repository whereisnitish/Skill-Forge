"""Synchronise the database catalogue with curated YAML content (idempotent)."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict

from django.db import transaction
from django.db.models import Max

from apps.evaluation.registry import evaluator_version

from .content_loader import (
    ContentBundle,
    challenge_version_payload,
    normalise_prerequisite,
    normalise_step,
    path_version_payload,
    stable_hash,
)
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

logger = logging.getLogger(__name__)


class SeedError(RuntimeError):
    pass


@transaction.atomic
def sync_catalog(bundle: ContentBundle) -> Counter:
    stats: Counter = Counter()
    categories = _sync_categories(bundle, stats)
    skills = _sync_skills(bundle, categories, stats)
    _sync_prerequisites(bundle, skills, stats)
    _sync_related(bundle, skills)
    _sync_challenges(bundle, skills, stats)
    _sync_paths(bundle, skills, stats)
    logger.info("catalog.synced", extra={"stats": dict(stats)})
    return stats


def _sync_categories(bundle: ContentBundle, stats: Counter) -> dict[str, SkillCategory]:
    result = {}
    for index, data in enumerate(bundle.categories):
        obj, created = SkillCategory.objects.update_or_create(
            slug=data["slug"],
            defaults={
                "name": data["name"],
                "description": data.get("description", ""),
                "icon": data.get("icon", "shapes"),
                "domain": data.get("domain", SkillCategory.Domain.SOFTWARE),
                "order": data.get("order", index),
            },
        )
        stats["categories_created" if created else "categories_synced"] += 1
        result[obj.slug] = obj
    return result


def _sync_skills(bundle: ContentBundle, categories: dict[str, SkillCategory], stats: Counter) -> dict[str, Skill]:
    result = {}
    for index, data in enumerate(bundle.skills):
        obj, created = Skill.objects.update_or_create(
            slug=data["slug"],
            defaults={
                "name": data["name"],
                "category": categories[data["category"]],
                "summary": data["summary"],
                "description": data.get("description", ""),
                "difficulty": data["difficulty"],
                "learning_objectives": list(data.get("objectives", [])),
                "review_interval_days": data.get("review_interval_days", 2),
                "order": index,
                "is_active": True,
            },
        )
        stats["skills_created" if created else "skills_synced"] += 1
        result[obj.slug] = obj
    stale = Skill.objects.filter(is_active=True).exclude(slug__in=result.keys())
    stats["skills_deactivated"] += stale.update(is_active=False)
    return result


def _sync_prerequisites(bundle: ContentBundle, skills: dict[str, Skill], stats: Counter) -> None:
    for data in bundle.skills:
        skill = skills[data["slug"]]
        desired = {}
        for raw in data.get("prerequisites", []) or []:
            prereq = normalise_prerequisite(raw)
            desired[skills[prereq["skill"]].pk] = prereq
        existing = {link.prerequisite_id: link for link in skill.prerequisite_links.all()}
        for prereq_id, link in existing.items():
            if prereq_id not in desired:
                link.delete()
                stats["prerequisites_removed"] += 1
        for prereq_id, prereq in desired.items():
            link = existing.get(prereq_id)
            if link is None:
                SkillPrerequisite.objects.create(
                    skill=skill,
                    prerequisite_id=prereq_id,
                    strength=prereq["strength"],
                    min_mastery=prereq["min_mastery"],
                )
                stats["prerequisites_created"] += 1
            elif (link.strength, link.min_mastery) != (prereq["strength"], prereq["min_mastery"]):
                link.strength = prereq["strength"]
                link.min_mastery = prereq["min_mastery"]
                link.save(update_fields=["strength", "min_mastery"])


def _sync_related(bundle: ContentBundle, skills: dict[str, Skill]) -> None:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for data in bundle.skills:
        for related in data.get("related", []) or []:
            adjacency[data["slug"]].add(related)
            adjacency[related].add(data["slug"])
    for slug, skill in skills.items():
        skill.related_skills.set([skills[r] for r in adjacency.get(slug, set())])


def _sync_challenges(bundle: ContentBundle, skills: dict[str, Skill], stats: Counter) -> None:
    seen: set[str] = set()
    for data in bundle.challenges:
        seen.add(data["slug"])
        challenge = Challenge.objects.filter(slug=data["slug"]).first()
        if challenge and challenge.kind != data["kind"] and challenge.attempts.exists():
            raise SeedError(f"Challenge {data['slug']!r} changed kind after learners attempted it; use a new slug.")
        fields = {
            "skill": skills[data["skill"]],
            "kind": data["kind"],
            "difficulty": data["difficulty"],
            "estimated_minutes": data["minutes"],
            "tags": list(data.get("tags", [])),
            "is_diagnostic": bool(data.get("diagnostic", False)),
            "source": Challenge.Source.CURATED,
            "review_status": Challenge.ReviewStatus.APPROVED,
            "is_active": True,
        }
        if challenge is None:
            challenge = Challenge.objects.create(slug=data["slug"], **fields)
            stats["challenges_created"] += 1
        else:
            for key, value in fields.items():
                setattr(challenge, key, value)
            challenge.save()
        challenge.secondary_skills.set([skills[s] for s in data.get("secondary_skills", []) or []])

        payload = challenge_version_payload(data)
        digest = stable_hash(payload)
        current = challenge.current_version
        if current is not None and current.content_hash == digest:
            stats["challenges_unchanged"] += 1
            continue
        number = (challenge.versions.aggregate(n=Max("number"))["n"] or 0) + 1
        version = ChallengeVersion.objects.create(
            challenge=challenge,
            number=number,
            title=data["title"],
            learning_objective=data["objective"],
            prompt=data["prompt"],
            content=data.get("content", {}),
            hints=list(data.get("hints", [])),
            solution=data.get("solution", ""),
            explanation=data.get("explanation", ""),
            evaluation_version=evaluator_version(data["kind"]),
            content_hash=digest,
        )
        ChallengeTestCase.objects.bulk_create(
            [
                ChallengeTestCase(
                    version=version,
                    order=index,
                    name=test["name"],
                    code=test["code"],
                    is_hidden=bool(test.get("hidden", False)),
                    weight=float(test.get("weight", 1.0)),
                )
                for index, test in enumerate(data.get("tests", []) or [], start=1)
            ]
        )
        challenge.current_version = version
        challenge.save(update_fields=["current_version", "updated_at"])
        stats["challenge_versions_created"] += 1

    stale = Challenge.objects.filter(is_active=True, source=Challenge.Source.CURATED).exclude(slug__in=seen)
    stats["challenges_deactivated"] += stale.update(is_active=False)


def _sync_paths(bundle: ContentBundle, skills: dict[str, Skill], stats: Counter) -> None:
    seen: set[str] = set()
    LearningPath.objects.filter(is_default_for_goal=True).update(is_default_for_goal=False)
    for index, data in enumerate(bundle.paths):
        seen.add(data["slug"])
        path, created = LearningPath.objects.update_or_create(
            slug=data["slug"],
            defaults={
                "name": data["name"],
                "tagline": data["tagline"],
                "description": data.get("description", ""),
                "goal_type": data["goal_type"],
                "icon": data.get("icon", "route"),
                "is_premium": bool(data.get("premium", False)),
                "is_default_for_goal": bool(data.get("default", False)),
                "is_active": True,
                "order": data.get("order", index),
            },
        )
        stats["paths_created" if created else "paths_synced"] += 1
        payload = path_version_payload(data)
        digest = stable_hash(payload)
        if path.current_version is not None and path.current_version.content_hash == digest:
            continue
        number = (path.versions.aggregate(n=Max("number"))["n"] or 0) + 1
        version = LearningPathVersion.objects.create(
            path=path, number=number, notes=data.get("version_notes", ""), content_hash=digest
        )
        for m_index, milestone_data in enumerate(data.get("milestones", []), start=1):
            milestone = PathMilestone.objects.create(
                version=version,
                order=m_index,
                title=milestone_data["title"],
                description=milestone_data.get("description", ""),
            )
            PathStep.objects.bulk_create(
                [
                    PathStep(
                        milestone=milestone,
                        order=s_index,
                        skill=skills[step["skill"]],
                        target_mastery=step["target"],
                    )
                    for s_index, step in enumerate(
                        (normalise_step(s) for s in milestone_data.get("steps", [])), start=1
                    )
                ]
            )
        path.current_version = version
        path.save(update_fields=["current_version", "updated_at"])
        stats["path_versions_created"] += 1
    stale = LearningPath.objects.filter(is_active=True).exclude(slug__in=seen)
    stats["paths_deactivated"] += stale.update(is_active=False)
