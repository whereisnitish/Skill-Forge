import pytest


@pytest.fixture
def seeded(transactional_db):
    """Live-server tests need committed data, so seed inside a transactional test."""
    from tests.factories import load_small_catalog

    load_small_catalog()


@pytest.fixture
def console_errors(page):
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors
