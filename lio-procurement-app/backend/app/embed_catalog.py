"""Embed catalog articles for semantic suggestions (spec 002).

Idempotent: only articles without a vector for the configured embedding model
are embedded (identical descriptions once). Safe to run on every startup; it
never fails the startup — without OPENAI_API_KEY, or if the service is
unreachable, suggestions fall back to exact-token matching and missing vectors
are filled on the first lookup. Run manually with:

    python -m app.embed_catalog
"""
import logging

import openai
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Organization
from app.services import catalog_search

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.openai_api_key:
        logger.info("Catalog embedding skipped: OPENAI_API_KEY is not set")
        return
    total = 0
    with SessionLocal() as db:
        for organization_id in db.scalars(select(Organization.id)):
            try:
                total += catalog_search.ensure_embeddings(
                    db, organization_id, catalog_search.openai_embedder
                )
            except openai.OpenAIError:
                db.rollback()
                logger.warning("Catalog embedding failed; will retry on first lookup")
                return
    logger.info("Catalog embedded: +%d articles (%s)", total, catalog_search.model_tag())


if __name__ == "__main__":
    main()
