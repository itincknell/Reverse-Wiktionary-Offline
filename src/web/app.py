"""
FastAPI application for Reverse Wiktionary serving.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.common.lexical_schema import ALLOWED_POS
from src.search.encoder import QueryEncoder, QueryEncoderConfig
from src.search.qdrant_search import QdrantSearchClient, QdrantSearchConfig
from src.search.schemas import SearchRequest
from src.search.service import SearchService
from src.web.config import WebSettings, load_settings
from src.web.state import SESSION_COOKIE, ClientSearchState, RedisSessionStore
from src.web.taxonomy import load_language_taxonomy


LOGGER = logging.getLogger(__name__)
PACKAGE_DIR = Path(__file__).resolve().parent


def create_app(settings: WebSettings | None = None) -> FastAPI:
    """
    Build the FastAPI application and register startup dependencies.

    Startup is intentionally strict: each worker loads its model, verifies
    Qdrant, verifies Redis, and builds the language cache before serving
    traffic.
    """
    settings = settings or load_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(title="Reverse Wiktionary", version="1.0.0")
    app.state.settings = settings
    app.state.available_langs = []
    app.state.available_pos = list(ALLOWED_POS)
    app.state.language_taxonomy = {"families": []}

    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    app.state.templates = templates

    app.mount(
        "/static",
        StaticFiles(directory=str(PACKAGE_DIR / "static")),
        name="static",
    )

    @app.on_event("startup")
    def startup() -> None:
        """
        Initialize worker-local model/search clients and shared Redis state.
        """
        encoder = QueryEncoder(
            QueryEncoderConfig(
                model_name=settings.model_name,
                device=settings.model_device,
            )
        )
        qdrant = QdrantSearchClient(
            QdrantSearchConfig(
                url=settings.qdrant_url,
                collection_name=settings.collection_name,
                hnsw_ef=settings.qdrant_hnsw_ef,
                acorn_max_selectivity=settings.qdrant_acorn_max_selectivity,
                exact_filtered=settings.search_exact_filtered,
            )
        )
        qdrant.verify_collection()
        session_store = RedisSessionStore(
            redis_url=settings.redis_url,
            ttl_seconds=settings.session_ttl_seconds,
        )
        session_store.ping()

        app.state.encoder = encoder
        app.state.qdrant = qdrant
        app.state.search_service = SearchService(encoder=encoder, qdrant=qdrant)
        app.state.session_store = session_store
        app.state.available_langs = qdrant.available_languages()
        app.state.language_taxonomy = load_language_taxonomy(
            settings.language_taxonomy_path,
            fallback_languages=app.state.available_langs,
        )
        app.state.available_pos = available_pos_from_metadata(settings.serving_metadata_path)

    @app.get("/health")
    def health() -> dict[str, object]:
        """
        Check dependencies required to serve search traffic.
        """
        qdrant = app.state.qdrant
        session_store = app.state.session_store
        encoder = app.state.encoder

        qdrant.verify_collection()
        session_store.ping()

        return {
            "status": "ok",
            "app_env": settings.app_env,
            "qdrant": "ok",
            "redis": "ok",
            "collection": settings.collection_name,
            "model": "loaded" if encoder.is_loaded() else "not_loaded",
            "vector_size": encoder.embedding_dimension,
            "available_langs": len(app.state.available_langs),
            "available_pos": len(app.state.available_pos),
            "language_taxonomy_families": len(app.state.language_taxonomy["families"]),
            "qdrant_hnsw_ef": settings.qdrant_hnsw_ef,
            "qdrant_acorn_max_selectivity": settings.qdrant_acorn_max_selectivity,
            "search_exact_filtered": settings.search_exact_filtered,
        }

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request) -> HTMLResponse:
        """
        Render the project/about page.
        """
        return templates.TemplateResponse("about.html", {"request": request})

    @app.post("/api/v1/search")
    def api_search(request: SearchRequest) -> dict[str, object]:
        """
        Stable public search API.
        """
        route_started = perf_counter()
        response = app.state.search_service.search(request)
        payload = response.model_dump()
        _log_search(
            route="api.search",
            search_response=response,
            route_total_ms=_elapsed_ms(route_started),
        )
        return payload

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        """
        Render the main search page with current session filter state.
        """
        session_id, should_set_cookie = _get_or_create_session_id(request)
        state = app.state.session_store.get(session_id, default_limit=settings.default_limit)

        template_response = templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "state": state,
                "available_langs": app.state.available_langs,
                "language_taxonomy": app.state.language_taxonomy,
                "available_pos": app.state.available_pos,
                "results": [],
                "has_more": False,
            },
        )
        _set_session_cookie(template_response, session_id, settings, should_set_cookie)
        return template_response

    @app.post("/ui/search", response_class=HTMLResponse)
    def ui_search(
        request: Request,
        query: str = Form(...),
        langs: list[str] = Form(default=[]),
        pos: list[str] = Form(default=[]),
        limit: int = Form(default=settings.default_limit),
    ) -> HTMLResponse:
        """
        Execute a new UI search and replace the result pane.
        """
        route_started = perf_counter()
        session_id, should_set_cookie = _get_or_create_session_id(request)
        search_request = SearchRequest(
            query=query,
            langs=langs,
            pos=pos,
            limit=min(limit, settings.max_limit),
            offset=0,
        )
        search_response = app.state.search_service.search(search_request)

        state = ClientSearchState(
            selected_langs=search_request.langs,
            selected_pos=search_request.pos,
            latest_query=search_request.query,
            limit=search_request.limit,
            next_offset=search_request.offset + search_request.limit,
            created_at_utc=app.state.session_store.get(
                session_id,
                default_limit=settings.default_limit,
            ).created_at_utc,
            updated_at_utc="",
        )
        app.state.session_store.save(session_id, state)

        template_response = templates.TemplateResponse(
            request=request,
            name="partials/results.html",
            context={
                "request": request,
                "results": search_response.results,
                "has_more": search_response.has_more,
                "next_offset": state.next_offset,
            },
        )
        _set_session_cookie(template_response, session_id, settings, should_set_cookie)
        _log_search(
            route="ui.search",
            search_response=search_response,
            route_total_ms=_elapsed_ms(route_started),
        )
        return template_response

    @app.post("/ui/search/more", response_class=HTMLResponse)
    def ui_search_more(request: Request) -> HTMLResponse:
        """
        Append the next page for the latest session query.
        """
        route_started = perf_counter()
        session_id, should_set_cookie = _get_or_create_session_id(request)
        state = app.state.session_store.get(session_id, default_limit=settings.default_limit)

        if not state.latest_query:
            template_response = templates.TemplateResponse(
                request=request,
                name="partials/results.html",
                context={
                    "request": request,
                    "results": [],
                    "has_more": False,
                    "next_offset": 0,
                },
            )
            _set_session_cookie(template_response, session_id, settings, should_set_cookie)
            return template_response

        search_request = SearchRequest(
            query=state.latest_query,
            langs=state.selected_langs,
            pos=state.selected_pos,
            limit=state.limit,
            offset=state.next_offset,
        )
        search_response = app.state.search_service.search(search_request)

        state.next_offset = search_request.offset + search_request.limit
        app.state.session_store.save(session_id, state)

        template_response = templates.TemplateResponse(
            request=request,
            name="partials/result_items.html",
            context={
                "request": request,
                "results": search_response.results,
                "has_more": search_response.has_more,
                "next_offset": state.next_offset,
            },
        )
        _set_session_cookie(template_response, session_id, settings, should_set_cookie)
        _log_search(
            route="ui.search_more",
            search_response=search_response,
            route_total_ms=_elapsed_ms(route_started),
        )
        return template_response

    return app


def _get_or_create_session_id(request: Request) -> tuple[str, bool]:
    """
    Return the current session ID, creating one when no cookie is present.
    """
    session_id = request.cookies.get(SESSION_COOKIE)

    if session_id:
        return session_id, False

    session_id = request.app.state.session_store.new_session_id()
    return session_id, True


def _set_session_cookie(
    response: Response,
    session_id: str,
    settings: WebSettings,
    should_set_cookie: bool,
) -> None:
    """
    Attach the session cookie to a response when a new session was created.
    """
    if not should_set_cookie:
        return

    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )


def _elapsed_ms(started: float) -> float:
    """
    Return elapsed milliseconds rounded for request logs.
    """
    return round((perf_counter() - started) * 1000, 2)


def available_pos_from_metadata(path: str) -> list[str]:
    """
    Return POS filters present in the current processed run.

    The shared lexical schema remains the allowlist. Runtime metadata narrows
    the visible UI filters to values that actually exist in the restored data.
    """
    metadata_path = Path(path)
    if not metadata_path.exists():
        return list(ALLOWED_POS)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    counts = metadata.get("pos_counts") or metadata.get("pos") or []
    if isinstance(counts, dict):
        counts = [
            {"pos": pos, "rows": rows}
            for pos, rows in counts.items()
        ]
    present = {
        str(item.get("pos"))
        for item in counts
        if isinstance(item, dict) and int(item.get("rows") or 0) > 0
    }

    if not present:
        return list(ALLOWED_POS)

    return [
        pos
        for pos in ALLOWED_POS
        if pos in present
    ]


def _configure_logging(log_level: str) -> None:
    """
    Ensure application timing logs are emitted under Uvicorn.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        LOGGER.addHandler(handler)

    LOGGER.setLevel(level)
    LOGGER.propagate = False


def _log_search(
    *,
    route: str,
    search_response: object,
    route_total_ms: float,
) -> None:
    """
    Log aggregate request metrics without recording raw query text.

    `route_overhead_ms` is route work outside the core search path. For UI
    routes it includes session IO and template rendering; for API routes it is
    the residual handler and serialization overhead.
    """
    route_overhead_ms = round(
        max(route_total_ms - search_response.timing_ms.total, 0.0),
        2,
    )

    LOGGER.info(
        "event=search route=%s query_length=%s langs_count=%s pos_count=%s "
        "limit=%s offset=%s embedding_ms=%s qdrant_ms=%s search_total_ms=%s "
        "route_overhead_ms=%s route_total_ms=%s result_count=%s has_more=%s",
        route,
        len(search_response.query),
        len(search_response.filters.langs),
        len(search_response.filters.pos),
        search_response.limit,
        search_response.offset,
        search_response.timing_ms.embedding,
        search_response.timing_ms.qdrant,
        search_response.timing_ms.total,
        route_overhead_ms,
        route_total_ms,
        len(search_response.results),
        search_response.has_more,
    )


app = create_app()
