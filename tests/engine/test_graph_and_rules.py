import pytest

from apps.engine.difficulty import difficulty_fit, target_difficulty
from apps.engine.eligibility import PrerequisiteEdge, readiness
from apps.engine.graph import CycleError, SkillGraph
from apps.engine.progress import recurring_misconceptions, streaks


def graph():
    # a -> b -> c, a -> d ; edges are (skill, prerequisite)
    return SkillGraph.from_edges("abcde", [("b", "a"), ("c", "b"), ("d", "a")])


def test_detects_cycles_and_self_loops():
    g = graph()
    assert g.find_cycle() is None
    g.add_edge("a", "c")
    cycle = g.find_cycle()
    assert cycle and cycle[0] == cycle[-1]
    with pytest.raises(CycleError):
        g.validate()
    with pytest.raises(CycleError):
        SkillGraph().add_edge("x", "x")


def test_would_create_cycle():
    g = graph()
    assert g.would_create_cycle("a", "c")  # c already depends on a
    assert not g.would_create_cycle("c", "d")
    assert g.would_create_cycle("b", "b")


def test_topological_order_and_depth():
    g = graph()
    order = g.topological_order()
    assert order.index("a") < order.index("b") < order.index("c")
    assert g.depth() == {"a": 0, "b": 1, "c": 2, "d": 1, "e": 0}


def test_dependency_importance_favours_foundations():
    importance = graph().dependency_importance()
    assert importance["a"] == 1.0
    assert importance["c"] == 0.0
    assert importance["b"] < importance["a"]


def test_readiness_blocks_only_on_required_prerequisites():
    edges = [PrerequisiteEdge(1, True, 0.55), PrerequisiteEdge(2, False, 0.55)]
    means = {1: 0.6, 2: 0.2}
    result = readiness(edges, means.__getitem__)
    assert result.ready and result.missing_recommended == (2,)
    means[1] = 0.3
    blocked = readiness(edges, means.__getitem__)
    assert not blocked.ready and blocked.missing_required == (1,)


def test_target_difficulty_tracks_mastery_and_momentum():
    assert target_difficulty(0.0, []) == 1.0
    assert target_difficulty(1.0, []) == 5.0
    base = target_difficulty(0.5, [])
    assert target_difficulty(0.5, [0.9, 0.9, 1.0]) > base
    assert target_difficulty(0.5, [0.1, 0.2]) < base
    assert target_difficulty(0.5, [], "stretch") > target_difficulty(0.5, [], "gentle")
    assert difficulty_fit(3, 3.0) == 1.0
    assert difficulty_fit(5, 1.0) == 0.4


def test_streaks_use_local_days_and_survive_until_end_of_today():
    from datetime import date, timedelta

    today = date(2026, 10, 22)
    days = [today - timedelta(days=i) for i in (1, 2, 3)] + [today - timedelta(days=10)]
    assert streaks(days, today) == (3, 3)  # practised yesterday: streak still alive today
    assert streaks([*days, today], today) == (4, 4)
    assert streaks([today - timedelta(days=2)], today) == (0, 1)
    assert streaks([], today) == (0, 0)


def test_recurring_misconceptions_need_repetition_within_window():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 10, 22, tzinfo=UTC)
    items = [
        ("gen-reuse", "Reuses exhausted generator", "conceptual", now - timedelta(days=1)),
        ("gen-reuse", "Reuses exhausted generator", "conceptual", now - timedelta(days=3)),
        ("one-off", "Once", "logic", now - timedelta(days=2)),
        ("old", "Old", "logic", now - timedelta(days=60)),
        ("old", "Old", "logic", now - timedelta(days=61)),
    ]
    result = recurring_misconceptions(items, now=now)
    assert [m.code for m in result] == ["gen-reuse"]
    assert result[0].count == 2
