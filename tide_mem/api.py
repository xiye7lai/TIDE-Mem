from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, status

from .auth import build_auth_dependency
from .config import Settings
from .db import MemoryDB
from .ingest import IdempotencyConflict, IngestionService
from .llm import LLMClient, LLMUnavailable
from .models import AddRequest, AddResponse, HealthResponse, SearchRequest, SearchResponse
from .retrieve import RetrievalService
from .text import stable_id

LOGGER = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Avoid request bodies or authorization headers in standard access logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _ttl_loop(db: MemoryDB, settings: Settings) -> None:
    while True:
        try:
            deleted = await db.purge_older_than(settings.ttl_days)
            if deleted:
                LOGGER.info("TTL cleanup removed %d evidence records", deleted)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("TTL cleanup failed")
        await asyncio.sleep(settings.ttl_cleanup_interval_seconds)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    _configure_logging(settings.log_level)

    db = MemoryDB(settings.db_path)
    llm = LLMClient(settings)
    ingestion = IngestionService(db, llm)
    retrieval = RetrievalService(settings, db, llm)
    verify_key = build_auth_dependency(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_runtime_ready()
        await db.initialize()
        await db.purge_older_than(settings.ttl_days)
        cleanup_task = asyncio.create_task(_ttl_loop(db, settings), name="tide-mem-ttl-cleanup")
        app.state.ready = True
        LOGGER.info(
            "started system=%s version=%s model=%s mode=%s",
            settings.app_name,
            settings.version,
            settings.llm_model,
            settings.llm_mode,
        )
        try:
            yield
        finally:
            app.state.ready = False
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
            await llm.close()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Evidence-only memory API for the Agent Memory Challenge 2026.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.llm = llm
    app.state.ingestion = ingestion
    app.state.retrieval = retrieval
    app.state.ready = False

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        if not app.state.ready or not await db.ping():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"reason": "service not ready"},
            )
        return HealthResponse(
            system=settings.app_name,
            version=settings.version,
            llm_model=settings.llm_model,
            llm_mode=settings.llm_mode,
        )

    @app.post(
        "/v1/memory/add",
        response_model=AddResponse,
        tags=["memory"],
        dependencies=[Depends(verify_key)],
    )
    async def add_memory(request: AddRequest) -> AddResponse:
        try:
            return await ingestion.add(request)
        except IdempotencyConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"reason": str(exc)},
            ) from exc
        except LLMUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"reason": "memory extraction temporarily unavailable"},
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            LOGGER.exception("Add failed request_id=%s", request.request_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"reason": "memory persistence failed"},
            ) from exc

    @app.post(
        "/v1/memory/search",
        response_model=SearchResponse,
        tags=["memory"],
        dependencies=[Depends(verify_key)],
    )
    async def search_memory(request: SearchRequest) -> SearchResponse:
        try:
            return await retrieval.search(request)
        except LLMUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"reason": "memory retrieval temporarily unavailable"},
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            LOGGER.exception(
                "Search failed user_hash=%s",
                stable_id(request.user_id, prefix="usr")[-10:],
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"reason": "memory retrieval failed"},
            ) from exc

    return app


app = create_app()
