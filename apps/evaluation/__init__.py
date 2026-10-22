"""Deterministic answer evaluation.

Evaluators are pure functions of (challenge content, learner response). They
never call AI providers: the AI mentor may *explain* a result, but scores and
mastery come only from these versioned evaluators.
"""
