"""SANKET API entry point.

Startup does real work: creates the schema for a fresh checkout, registers the data
catalogue, seeds the demo accounts and starts the ingestion worker. If no model
credentials are configured the server still runs - the agent then answers from
retrieved data only, and says so - because the deterministic half of this product is
the part that must never be faked.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# `agent.model` reads configuration and, at call time only, tries the provider's SDK; nothing
# here imports strands, so a machine without the agent installed still starts the API.
from agent import model as agent_model
from backend.app.api import api_router
from backend.app.config import REPO_ROOT, settings
from backend.app.db import SessionLocal, init_db
from backend.app.scheduler import IngestionWorker
from backend.app.services import ingestion
from backend.app.services import users as user_service
from shared.timeutils import iso, utcnow

logging.basicConfig(
    level=logging.INFO if settings.environment == "development" else logging.WARNING,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sanket.app")

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
GEO_DIR = REPO_ROOT / "Data" / "geo"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        ingestion.ensure_sources(db)
        if settings.allow_demo_accounts:
            user_service.ensure_demo_users(db)
        source_count = len(ingestion.source_health(db))
    finally:
        db.close()

    worker = IngestionWorker(SessionLocal, tick_seconds=settings.scheduler_poll_seconds)
    if settings.ingestion_enabled:
        worker.start()
    app.state.worker = worker

    # Reported from the same status object /api/agent/status answers with, rather than from the
    # name of a provider: `LLM_PROVIDER=gemini` with an empty key is not a reachable model, and a
    # startup line reading "model provider gemini" tells whoever booted this that the language
    # layer is on when it is not.
    model_status = agent_model.status()
    logger.info(
        "SANKET ready - %s sources registered, ingestion %s, model %s",
        source_count,
        "on" if settings.ingestion_enabled else "off",
        f"{model_status.provider}/{model_status.model_id}"
        if model_status.available
        else f"NOT USABLE - {model_status.reason}",
    )
    if not settings.secret_key:
        logger.warning(
            "SANKET_SECRET_KEY is not set - session tokens are signed with a development "
            "default. Do not expose this server beyond localhost."
        )
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(
    title="SANKET - Disaster Intelligence and Community Response",
    description=(
        "Official-source disaster intelligence for Nepal with a two-way community channel. "
        "Every fact in this API carries its source, its timestamp and its freshness."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def provenance_header(request: Request, call_next):
    """Every response states when it was produced, so a cached screen can never be
    mistaken for a live one."""
    response = await call_next(request)
    response.headers["X-Sanket-Generated-At"] = iso(utcnow())
    response.headers["X-Sanket-Mode"] = "demo" if settings.demo_mode else "live"
    return response


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    # Service functions raise ValueError for "the caller asked for something the
    # data does not support" - surface the reason instead of a bare 500.
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(api_router, prefix="/api")

# Boundary polygons are the one thing the map needs before it can draw anything, and a
# filesystem path in /map/layers is not a URL a browser can fetch. Served read-only and
# unauthenticated: district boundaries are public data, and a signed-out reader on the
# community side still needs to see the shape of Nepal.
if GEO_DIR.is_dir():
    app.mount("/geo", StaticFiles(directory=GEO_DIR), name="geo")


# The root of the site belongs to whichever product is actually installed here. Answering the
# pointer JSON at `/` while the built SPA sat one path deeper (`/index.html`) meant a first-time
# reader saw four lines of metadata and concluded the frontend had not been built - and the
# pointer's own `"frontend": "served here"` was false at the exact URL it was served from.
@app.get("/", include_in_schema=False, response_model=None)
def root() -> FileResponse | dict[str, str]:
    if (FRONTEND_DIST / "index.html").is_file():
        return FileResponse(FRONTEND_DIST / "index.html")
    return {
        "name": "SANKET",
        "docs": "/api/docs",
        "health": "/api/health",
        "frontend": "run `npm run build` in frontend/, or `npm run dev` on port 5173",
    }


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=Path(FRONTEND_DIST) / "assets"), name="assets")

    # response_model=None: FastAPI cannot build a response model from a union of two
    # Response subclasses, and this route returns a document or an error, never data.
    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def serve_frontend(full_path: str) -> FileResponse | JSONResponse:
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(candidate)
        if full_path.startswith("api/"):
            # This handler exists to serve the client-side router, and the API router has
            # already had its chance at this path. Answering 200 with the app shell for a
            # misspelled endpoint turns a wrong path into a JSON parse error somewhere far
            # from the typo - and, in a browser, into a layer that silently has no data.
            return JSONResponse(
                status_code=404,
                content={"detail": f"No API route at /{full_path}", "docs": "/api/docs"},
            )
        # Client-side routing owns everything below the root document.
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/frontend-not-built", include_in_schema=False)
    def frontend_missing() -> dict[str, str]:
        return {
            "detail": "The frontend has not been built. Run `npm run dev` (port 5173) "
            "or `npm run build` in ./frontend to serve it from this server."
        }
