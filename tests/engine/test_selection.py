from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from apps.engine.eligibility import Readiness
from apps.engine.explain import ExplanationContext, explain
from apps.engine.selection import (
    CandidateChallenge,
    ChallengeHistory,
    SelectionRequest,
    SkillContext,
    score_candidate,
    select_challenge,
)

NOW = datetime(2026, 10, 1, 10, tzinfo=UTC)
READY = Readiness(ready=True)


def skill(skill_id: int, **kw) -> SkillContext:
    defaults = {
        "skill_id": skill_id,
        "name": f"Skill {skill_id}",
        "difficulty": 2,
        "mean": 0.5,
        "evidence_count": 3,
        "urgency": 0.0,
        "goal_relevance": 0.6,
        "dependency_importance": 0.0,
        "readiness": READY,
    }
    defaults.update(kw)
    return SkillContext(**defaults)


def challenge(challenge_id: int, skill_id: int, **kw) -> CandidateChallenge:
    defaults = {
        "challenge_id": challenge_id,
        "version_id": challenge_id,
        "skill_id": skill_id,
        "kind": "multiple_choice",
        "difficulty": 2,
        "minutes": 3,
    }
    defaults.update(kw)
    return CandidateChallenge(**defaults)


def request(**kw) -> SelectionRequest:
    defaults = {"seed": "u1:2026-10-01:1", "now": NOW, "minutes_remaining": 15, "exploration_rate": 0.0, "top_k": 1}
    defaults.update(kw)
    return SelectionRequest(**defaults)


def test_weak_skills_are_prioritised():
    skills = {1: skill(1, mean=0.2), 2: skill(2, mean=0.85)}
    pick = select_challenge([challenge(10, 1), challenge(20, 2)], skills, {}, request())
    assert pick.scored.candidate.skill_id == 1


def test_prerequisites_are_enforced():
    skills = {1: skill(1, mean=0.1, readiness=Readiness(ready=False, missing_required=(3,))), 2: skill(2, mean=0.9)}
    pick = select_challenge([challenge(10, 1), challenge(20, 2)], skills, {}, request())
    assert pick.scored.candidate.skill_id == 2


def test_due_review_beats_slightly_weaker_skill_and_is_explained():
    skills = {1: skill(1, mean=0.45), 2: skill(2, mean=0.6, urgency=1.0, last_practiced_at=NOW - timedelta(days=4))}
    pick = select_challenge([challenge(10, 1), challenge(20, 2)], skills, {}, request())
    assert pick.scored.candidate.skill_id == 2
    assert pick.explanation.code == "review_due"
    assert "4 days ago" in pick.explanation.text


def test_recently_attempted_challenges_are_skipped():
    skills = {1: skill(1, mean=0.2)}
    histories = {10: ChallengeHistory(attempts=1, last_attempted_at=NOW - timedelta(hours=2), best_score=0.0)}
    pick = select_challenge([challenge(10, 1), challenge(11, 1)], skills, histories, request())
    assert pick.scored.candidate.challenge_id == 11


def test_returns_none_when_nothing_is_eligible():
    skills = {1: skill(1, readiness=Readiness(ready=False, missing_required=(9,)))}
    assert select_challenge([challenge(10, 1)], skills, {}, request()) is None
    assert select_challenge([], {}, {}, request()) is None


def test_excluded_and_unavailable_kinds_are_filtered():
    skills = {1: skill(1, mean=0.1)}
    cands = [challenge(10, 1), challenge(11, 1, kind="python_code")]
    pick = select_challenge(
        cands, skills, {}, request(excluded_challenge_ids=frozenset({10}), unavailable_kinds=frozenset({"python_code"}))
    )
    assert pick is None


def test_selection_is_deterministic_for_a_seed():
    skills = {i: skill(i, mean=0.3 + i * 0.01) for i in range(1, 6)}
    cands = [challenge(i * 10, i) for i in range(1, 6)]
    picks = {
        select_challenge(cands, skills, {}, request(top_k=3, seed="same")).scored.candidate.challenge_id
        for _ in range(5)
    }
    assert len(picks) == 1


def test_controlled_variation_across_days():
    skills = {i: skill(i, mean=0.4) for i in range(1, 4)}
    cands = [challenge(i * 10, i) for i in range(1, 4)]
    picks = {
        select_challenge(cands, skills, {}, request(top_k=3, seed=f"u1:day{d}")).scored.candidate.challenge_id
        for d in range(30)
    }
    assert len(picks) > 1


def test_variety_penalises_skills_already_recommended_today():
    skills = {1: skill(1, mean=0.3), 2: skill(2, mean=0.35)}
    pick = select_challenge(
        [challenge(10, 1), challenge(20, 2)], skills, {}, request(skills_recommended_today=Counter({1: 2}))
    )
    assert pick.scored.candidate.skill_id == 2


def test_difficulty_fit_prefers_challenges_near_target():
    skills = {1: skill(1, mean=0.25)}  # target difficulty 2
    easy = score_candidate(challenge(10, 1, difficulty=2), skills[1], ChallengeHistory(), request())
    hard = score_candidate(challenge(11, 1, difficulty=5), skills[1], ChallengeHistory(), request())
    assert easy.score > hard.score


def test_time_budget_and_format_preferences():
    skills = {1: skill(1)}
    base = request(preferred_kinds=frozenset({"debugging"}))
    long = score_candidate(challenge(10, 1, minutes=30), skills[1], ChallengeHistory(), base)
    preferred = score_candidate(challenge(11, 1, kind="debugging"), skills[1], ChallengeHistory(), base)
    other = score_candidate(challenge(12, 1), skills[1], ChallengeHistory(), base)
    assert preferred.score > other.score > long.score


def test_exploration_probes_unmeasured_skills():
    skills = {1: skill(1, mean=0.2, evidence_count=5), 2: skill(2, mean=0.3, evidence_count=0)}
    pick = select_challenge(
        [challenge(10, 1), challenge(20, 2, is_diagnostic=True)], skills, {}, request(exploration_rate=1.0)
    )
    assert pick.explored
    assert pick.scored.candidate.skill_id == 2
    assert pick.explanation.code == "explore_unmeasured"


def test_insufficient_evidence_still_produces_a_reasoned_pick():
    skills = {
        1: skill(
            1, mean=0.25, evidence_count=0, goal_relevance=0.85, milestone_title="First", in_current_milestone=True
        )
    }
    pick = select_challenge([challenge(10, 1)], skills, {}, request(path_name="Python Craftsman"))
    assert pick.explanation.code == "next_in_path"
    assert "Python Craftsman" in pick.explanation.text


def ctx(**kw) -> ExplanationContext:
    defaults = {
        "skill_name": "Generators",
        "urgency": 0.0,
        "weakness": 0.5,
        "goal_relevance": 0.6,
        "dependency_importance": 0.2,
        "contributions": {"weakness": 0.2, "review_urgency": 0.0},
        "mean": 0.5,
        "evidence_count": 3,
    }
    defaults.update(kw)
    return ExplanationContext(**defaults)


def test_explanations_are_deterministic_and_specific():
    assert (
        explain(ctx(recent_failures=2)).text == "Selected because you struggled with Generators in 2 recent exercises."
    )
    assert explain(ctx(blocking_for=("Async",))).text == "Selected to practise Generators, a prerequisite for Async."
    assert explain(ctx(is_focus_skill=True)).code == "goal_priority"
    assert explain(ctx(urgency=0.8, days_since_practice=1)).text.endswith("you last practised it yesterday.")
    misconception = explain(ctx(recent_failures=1, top_misconception="Reuses exhausted generators"))
    assert misconception.code == "recent_struggle" and "Reuses exhausted generators" in misconception.text
    assert explain(ctx()) == explain(ctx())


def test_components_follow_configured_weights():
    skills = {1: skill(1, mean=0.0, urgency=1.0, goal_relevance=1.0, dependency_importance=1.0)}
    scored = score_candidate(challenge(10, 1), skills[1], ChallengeHistory(), request())
    assert scored.priority == 1.0
    custom = score_candidate(
        challenge(10, 1), skills[1], ChallengeHistory(), replace(request(), weights={"weakness": 1.0})
    )
    assert custom.components["review_urgency"] == 0
