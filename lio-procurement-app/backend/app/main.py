import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import (
    articles,
    auth,
    booking_rules,
    catalog,
    classification,
    commodity_groups,
    extraction,
    organizations,
    pdf,
    requests,
    suppliers,
)


def create_app() -> FastAPI:
    # Application INFO logs (e.g. one diagnostics line per extraction) are off
    # by default because only uvicorn configures its own loggers.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = FastAPI(
        title="askLio Procurement API",
        version="0.1.0",
        description="FastAPI backend for the askLio procurement app.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(requests.router)
    app.include_router(organizations.router)
    app.include_router(commodity_groups.router)
    app.include_router(suppliers.router)
    app.include_router(articles.router)
    app.include_router(catalog.router)
    app.include_router(classification.router)
    app.include_router(booking_rules.router)
    app.include_router(pdf.router)
    app.include_router(extraction.router)

    return app


app = create_app()
