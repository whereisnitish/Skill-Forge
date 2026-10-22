"""SkillForge adaptive learning engine.

Pure, deterministic domain logic with no Django model imports. Services in
`apps.learning.services` load data, call these functions and persist results,
which keeps every decision unit-testable and the models replaceable.
"""
