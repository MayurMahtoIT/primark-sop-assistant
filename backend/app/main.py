"""FastAPI entrypoint for the SOP assistant."""

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.auth import Authenticator
from app.aws import clients
from app.config import Settings, get_settings
from app.logging_conf import configure_logging, request_id_var
from app.rag.embeddings import Embedder
from app.rag.guardrails import BedrockGuardrail, NullGuardrail
from app.rag.index import ensure_schema
from app.rag.llm import LLM
from app.rag.retrieval import PostgresRetriever
from app.rag.service import RagService
from app.rag.sessions import DynamoSessionStore, InMemorySessionStore
from app.vectorstore import close_connection_pool, get_connection_pool

logger = logging.getLogger("app")
STATIC_DIR = Path(__file__).parent / "static"

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def build_services(app: FastAPI, settings: Settings) -> None:
    guardrail_bedrock = (
        clients.bedrock_runtime(settings, settings.aws_region) if settings.guardrail_id else None
    )

    db_pool = get_connection_pool(settings)
    ensure_schema(db_pool, settings)

    if settings.guardrail_id:
        guardrail = BedrockGuardrail(guardrail_bedrock, settings.guardrail_id, settings.guardrail_version)
    else:
        logger.warning("guardrails_disabled_local_only")
        guardrail = NullGuardrail()

    sessions = (
        DynamoSessionStore(clients.dynamodb_table(settings), settings.session_ttl_seconds)
        if settings.sessions_table
        else InMemorySessionStore()
    )
    retriever = PostgresRetriever(
        db_pool,
        table=settings.postgres_table,
        max_per_sop=settings.max_chunks_per_sop,
        candidates=settings.retrieval_candidates,
    )
    app.state.retriever = retriever
    app.state.sessions = sessions
    app.state.authenticator = Authenticator(settings)
    app.state.rag = RagService(
        settings=settings,
        embedder=Embedder(
            settings.mesh_api_key,
            settings.mesh_base_url,
            settings.embedding_model_name,
            settings.embedding_dimensions,
        ),
        retriever=retriever,
        llm=LLM(
            settings.mesh_api_key,
            settings.mesh_base_url,
            settings.generation_model_id,
            settings.max_output_tokens,
            settings.temperature,
        ),
        guardrail=guardrail,
        sessions=sessions,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_for_serving()
    build_services(app, settings)
    logger.info("startup_complete", extra={"ctx": {"env": settings.env}})
    try:
        yield
    finally:
        close_connection_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Primark Oracle DBA SOP API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if settings.env == "prod" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.env == "prod" else "/openapi.json",
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["GET", "POST"],
            allow_headers=["authorization", "content-type"],
            max_age=600,
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        response.headers["content-security-policy"] = CSP
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/v1/"):
            response.headers["cache-control"] = "no-store"
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled_error")
        return JSONResponse(
            {"detail": "Something went wrong. Please try again.", "request_id": request_id_var.get()},
            status_code=500,
        )

    app.include_router(router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")  # keep last
    return app


app = create_app()
