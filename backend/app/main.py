import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent.errors import (
    AgentConfigurationError,
    GraphExecutionError,
    LLMAuthError,
    LLMBadRequestError,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    StructuredOutputError,
)
from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import check_database_connection, dispose_engine, init_engine
from app.core.exceptions import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DatabaseError,
    NotFoundError,
)
from app.core.logging import configure_logging
from app.rag.errors import (
    RAGDocumentUnavailableError,
    RAGIngestionFailureError,
    RAGUploadTooLargeError,
    RAGUploadValidationError,
)

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(debug=settings.is_debug)
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)

    init_engine(settings)
    if not await check_database_connection():
        logger.warning(
            "Database is not reachable at startup; the API will serve but "
            "GET /api/v1/health/db will report unavailable"
        )

    yield

    await dispose_engine()
    logger.info("%s stopped", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Digital Twin - Car Health Monitoring Platform backend. "
        "Phase 1 provides vehicle registration and raw telemetry storage."
    ),
    lifespan=lifespan,
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": f"{exc.resource} not found"})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": exc.detail})


@app.exception_handler(DatabaseError)
async def database_error_handler(request: Request, exc: DatabaseError) -> JSONResponse:
    logger.error("Database error while handling %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": exc.detail})


@app.exception_handler(AuthorizationError)
async def authorization_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": exc.detail})


@app.exception_handler(RAGUploadValidationError)
async def rag_upload_validation_handler(
    request: Request, exc: RAGUploadValidationError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RAGUploadTooLargeError)
async def rag_upload_too_large_handler(
    request: Request, exc: RAGUploadTooLargeError
) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(exc)})


@app.exception_handler(RAGIngestionFailureError)
async def rag_ingestion_failure_handler(
    request: Request, exc: RAGIngestionFailureError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(RAGDocumentUnavailableError)
async def rag_document_unavailable_handler(
    request: Request, exc: RAGDocumentUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(LLMTimeoutError)
async def llm_timeout_handler(request: Request, exc: LLMTimeoutError) -> JSONResponse:
    logger.error("LLM timeout while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=504, content={"detail": "LLM provider timed out", "error_code": exc.error_code}
    )


@app.exception_handler(LLMRateLimitError)
async def llm_rate_limit_handler(request: Request, exc: LLMRateLimitError) -> JSONResponse:
    logger.error("LLM rate limit while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "LLM provider is rate limiting requests", "error_code": exc.error_code},
    )


@app.exception_handler(LLMAuthError)
async def llm_auth_handler(request: Request, exc: LLMAuthError) -> JSONResponse:
    logger.error("LLM auth failure while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=502,
        content={"detail": "LLM provider authentication failed", "error_code": exc.error_code},
    )


@app.exception_handler(LLMProviderUnavailableError)
async def llm_unavailable_handler(
    request: Request, exc: LLMProviderUnavailableError
) -> JSONResponse:
    logger.error("LLM provider unavailable while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=502,
        content={"detail": "LLM provider unavailable", "error_code": exc.error_code},
    )


@app.exception_handler(LLMBadRequestError)
async def llm_bad_request_handler(request: Request, exc: LLMBadRequestError) -> JSONResponse:
    logger.error("LLM bad request while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=502,
        content={"detail": "LLM provider rejected the request", "error_code": exc.error_code},
    )


@app.exception_handler(LLMProviderError)
async def llm_provider_error_handler(request: Request, exc: LLMProviderError) -> JSONResponse:
    logger.error("LLM provider error while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=502,
        content={"detail": "LLM provider error", "error_code": exc.error_code},
    )


@app.exception_handler(StructuredOutputError)
async def structured_output_handler(request: Request, exc: StructuredOutputError) -> JSONResponse:
    logger.error(
        "Structured output invalid while handling %s %s: error_code=%s provider=%s model=%s detail=%s",
        request.method,
        request.url.path,
        exc.error_code,
        getattr(exc, "provider", "unknown"),
        getattr(exc, "model", "unknown"),
        exc,
    )
    return JSONResponse(
        status_code=502,
        content={"detail": "LLM structured output invalid", "error_code": exc.error_code},
    )


@app.exception_handler(AgentConfigurationError)
async def agent_configuration_handler(
    request: Request, exc: AgentConfigurationError
) -> JSONResponse:
    logger.error("Agent configuration error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Agent is not configured correctly", "error_code": exc.error_code},
    )


@app.exception_handler(GraphExecutionError)
async def graph_execution_handler(request: Request, exc: GraphExecutionError) -> JSONResponse:
    logger.error(
        "Agent graph execution error while handling %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Agent workflow failed", "error_code": exc.error_code},
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.error("Unhandled application error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _jsonable_validation_errors(errors: list[dict]) -> list[dict]:
    """Strip anything that is not JSON-serializable from validation errors.

    ``exc.errors()`` can carry live objects in ``ctx`` (e.g. the ``ValueError``
    raised when a plain form value is posted to a file field) and non-primitive
    ``input`` values (e.g. ``UploadFile``). Returning those verbatim makes the
    422 response itself unserializable, which would turn a client error into a
    500. Only ``type``/``loc``/``msg`` are contractual here, so everything else
    is dropped unless it is a plain JSON primitive.
    """
    out: list[dict] = []
    for error in errors:
        item = {
            "type": str(error.get("type", "")),
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": str(error.get("msg", "")),
        }
        raw_input = error.get("input")
        if isinstance(raw_input, str | int | float | bool | list | dict | None):
            item["input"] = raw_input
        out.append(item)
    return out


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"detail": _jsonable_validation_errors(exc.errors())}
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unexpected error while handling %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs"}
