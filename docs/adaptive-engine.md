# Adaptive engine design

The engine (`apps/engine`) is deterministic, versioned and free of Django model imports. Services in
`apps/learning/services` load data, call it, and persist both the decision and the reasoning behind it.

| Component | Module | Version tag |
|---|---|---|
| Mastery estimation | `mastery.py` | `beta-evidence-v1` |
| Review scheduling | `scheduling.py` | `sm2-lite-v1` |
| Challenge selection | `selection.py` | `weighted-priority-v1` |
| Prerequisite graph | `graph.py` | — |
| Eligibility | `eligibility.py` | — |
| Difficulty progression | `difficulty.py` | — |
| Explanations | `explain.py` | — |
| Streaks, recurring mistakes | `progress.py` | — |

Every persisted output records the version that produced it (`SkillMastery.model_version`,
`SkillEvidence.model_version`, `ReviewSchedule.algorithm_version`, `Recommendation.strategy_version`,
`AttemptEvaluation.evaluator_version`, `ChallengeVersion.evaluation_version`). To replace a model, implement the same
interface, give it a new version string and return it from `get_model()` / `get_scheduler()`.

## 1. Skill graph

Skills form a directed acyclic graph of prerequisites (`required` or `recommended`, each with a `min_mastery`
threshold). Cycles are rejected in three places: the YAML validator, `SkillPrerequisite.clean()` (admin) and the
`check_skill_graph` management command. The graph provides topological order, depth (used for the skill-map
layout), ancestors/descendants and **dependency importance** — the share of in-scope skills that depend on a skill.

## 2. Mastery model (`beta-evidence-v1`)

Each (learner, skill) holds a Beta(α, β) belief about the probability of succeeding on a typical challenge.

**Prior.** Two pseudo-observations centred on a mean from the self-reported level (beginner 0.25,
intermediate 0.40, advanced 0.50) minus 0.06 per difficulty step above 2, clamped to [0.05, 0.60]. Self-reported
level is weak evidence by design: a handful of real answers outweigh it.

**Update for one observation** (score *s* ∈ [0, 1], partial credit allowed):

1. *Time decay.* Evidence above the prior decays with a 45-day half-life:
   `α ← α₀ + (α − α₀)·0.5^(days/45)`, likewise β.
2. *Recency.* Each new observation discounts older evidence by 0.92 (an effective memory of roughly 12 attempts).
3. *Difficulty.* With `rel = challenge difficulty − skill difficulty`:
   success weight `clamp(1 + 0.2·rel, 0.5, 1.5)`, failure weight `clamp(1 − 0.2·rel, 0.5, 1.5)`.
4. *Independence.* Hints scale success credit by `1 − 0.5·(hints used / hints available)`; a revealed solution
   scales it to 0.15 and adds 0.25 failure evidence.
5. *Delayed recall.* A pass (≥ 0.7) at least 2 days after the last practice multiplies success credit by 1.25 and
   counts as a delayed success.
6. *Format variety.* The first attempt in a new format (after the first ever) is weighted ×1.1.
7. `α += w·s·…`, `β += w·(1−s)·…` where `w` is 1.0 for the primary skill and 0.4 for secondary skills.
8. Evidence is capped at 25 pseudo-observations.

**Outputs.** Mean, standard deviation, a conservative lower bound (mean − 1 sd), a confidence label (low if fewer
than 3 attempts or sd > 0.17; medium if sd > 0.11; otherwise high) and a level with **evidence gates**:

| Level | Requirement |
|---|---|
| Not started | no primary evidence |
| Exploring | otherwise |
| Developing | ≥ 2 attempts and mean ≥ 0.40 |
| Proficient | ≥ 4 attempts and mean ≥ 0.70 |
| Mastered | ≥ 6 attempts, mean ≥ 0.85, sd ≤ 0.12 **and** at least one successful delayed recall |

One easy correct answer therefore yields *Exploring, low confidence* — never *Mastered*. Time spent is stored
for the learner's reference and is **never** an input to mastery.

## 3. Review scheduling (`sm2-lite-v1`)

Per (learner, skill). Score and assistance map to a recall quality *q* ∈ 0–5
(`round(5s)`, minus one per hint up to two, capped at 1 if the solution was revealed).

| Situation | Effect |
|---|---|
| First exposure, *q* ≥ 3 | interval = the skill's `review_interval_days` |
| First exposure, *q* < 3 | due again in 1 day |
| Review, *q* < 3 (lapse) | interval → 1 day, ease −0.2 (min 1.3), lapses +1 |
| Review before half the interval elapsed | recorded, schedule unchanged (cramming doesn't extend intervals) |
| Successful review | rep 1 → base, rep 2 → max(3, 3×base), then `max(interval, min(elapsed, 2×interval)) × ease`; ease adjusted by the SM-2 formula; capped at 120 days |

A missed **placement** question does not create a review (it means "not learned yet", not "forgotten").
Every decision writes a `ReviewRecord` (one per attempt — the idempotency key), storing previous/new interval
and due date and the outcome.

**Urgency** (selection input): 0 when not due today; 0.4 when due later in the learner's local day; 0.6 → 1.0 as a
review becomes overdue relative to its interval.

## 4. Eligibility

Before scoring, candidates are removed if:

* any **required** prerequisite's current mean is below its `min_mastery` (recommended prerequisites only apply a
  ×0.85 penalty);
* the evaluator for the challenge kind is unavailable (e.g. Python coding without the sandbox);
* the challenge is already in today's plan (including skipped ones);
* the learner attempted it within the last 20 hours.

The onboarding placement check deliberately ignores prerequisites so experienced learners can demonstrate later
skills immediately.

## 5. Selection (`weighted-priority-v1`)

The candidate universe is the goal's path skills, focus skills, their prerequisites (inheriting half their
relevance) and any skill with a review schedule.

```
priority = 0.35·weakness + 0.25·review_urgency + 0.20·goal_relevance + 0.20·dependency_importance
```

* weakness = 1 − current mean
* goal relevance: focus skill 1.0 · current milestone 0.85 · next milestone 0.6 · later milestones 0.4 ·
  completed milestones 0.3 · review-only 0.3 · prerequisites inherit 0.5× their dependant's relevance
* dependency importance: share of in-scope skills that depend on the skill

Weights come from settings (`ENGINE_WEIGHT_*`). **This is an initial heuristic, not a validated formula.**

Multiplicative modifiers: difficulty fit `max(0.4, 1 − 0.18·|d − target|)` where target difficulty is
`1 + 4·mean`, +0.5 after three strong results, −0.75 after two weak ones, ±0.5 for the gentle/stretch preference;
preferred formats ×1.15 (others ×0.9); focus skills ×1.5; already-solved challenges ×0.45 (×0.75 when a review is
due); unsolved retries ×0.9; repeats of a skill already planned today ×0.6ⁿ; challenges longer than the remaining
time budget ×0.35.

**Controlled variation.** A random source seeded with `user:local-date:slot` makes picks reproducible (stable
across page reloads, testable) yet different day to day. With probability `ENGINE_EXPLORATION_RATE` (0.15) an
unmeasured, eligible skill is probed — preferring its diagnostic question — to discover gaps. Otherwise the pick is
a weighted draw (weights = score²) among the top `ENGINE_TOP_K` (3) candidates.

**Daily plan.** Only the next recommendation exists at any time. It is created when the learner opens Today (or by
the 04:00 local pre-build task) and re-created after each completion or skip, until the day's minute budget is
used. "Practise one more" adds one beyond the budget.

## 6. Explanations

`explain()` maps the context to a reason code, in priority order, with deterministic text:

| Code | Example text |
|---|---|
| `explore_unmeasured` | We haven't measured Async programming yet — this quick check helps calibrate your plan. |
| `review_due` | Scheduled because Closures is due for review — you last practised it 4 days ago. |
| `recent_struggle` | Selected because you struggled with Generators in 2 recent exercises (recurring issue: …). |
| `goal_priority` | Selected because your goal prioritises ORM query optimisation. |
| `next_in_path` | Next step in "Idiomatic foundations" on your Python Craftsman path. |
| `prerequisite` | Selected to practise Comprehensions, a prerequisite for Iterators & generators. |
| `build_mastery` | Builds toward proficiency in SQL joins — your current estimate is 42%. |

The code, rendered text and full component breakdown (priority, modifiers, target difficulty, relevance) are
stored on the `Recommendation`.

## 7. Evaluation

| Kind | Evaluator | Scoring |
|---|---|---|
| Multiple choice | `choice-v1` | exact; "select all" = (correct − wrong) / total correct, floored at 0 |
| Short answer | `short-answer-v1` | normalised exact match, regex patterns, numeric tolerance, partial answers, known wrong answers with misconceptions |
| Concept explanation, code review | `rubric-v1` | weighted key-idea criteria (prefix/regex matching); a missed *required* criterion caps at 0.6; below `min_words` caps at 0.5; long passages copied from the prompt or shown code are ignored |
| Debugging | `debugging-v1` | 40% correct line + 60% explanation rubric |
| Python code | `python-tests-v1` | weighted share of curated tests passed in the sandbox; syntax errors fail without execution; hidden test details are redacted |

Pass = score ≥ 0.8; partial = 0.3–0.8. The learner model is only updated after a successful evaluation; if the
sandbox is unavailable the attempt stays queued (retried) and never counts as passed.

## 8. Limitations and next steps

* The heuristics are plausible defaults, not fitted to data. Once real usage exists: calibrate the prior and
  weights, compare against Elo/IRT- or Bayesian-knowledge-tracing-style models offline, and A/B test
  selection strategies (the versioning above exists for this).
* Keyword rubrics check coverage of key ideas, not correctness of reasoning or writing quality; a learner who
  writes the right words in the wrong order can score well. The UI says so. A reviewed, rubric-anchored AI grader
  (with deterministic guard-rails) is a possible future addition.
* Mastery is per skill; cross-skill transfer is only modelled through secondary-skill evidence.
