import pytest

from app.core.config import settings
from app.services import catalog_search


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Tests never call the AI service, even if a developer's .env has a key.

    Tests that exercise AI-backed code inject stub providers explicitly.
    """
    monkeypatch.setattr(settings, "openai_api_key", None)
    catalog_search.reset_caches()
    yield
    catalog_search.reset_caches()
