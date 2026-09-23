"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api.health import router as health_router
from app.api.catalog import router as catalog_router
from app.api.canvas import router as canvas_router, canvas_error_handler
from app.services.canvas_errors import CanvasError
from app.api.documents import router as document_router, document_error_handler
from app.services.document_errors import DocumentError
from app.api.knowledge import router as knowledge_router, ai_error_handler
from app.services.ai_errors import AIError
from app.api.sync import router as sync_router
from app.api.study import router as study_router
from app.core.config import Settings
from app.core.database import build_engine, create_session_factory, init_db

def create_app(database_engine: Engine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Importing this module does not open or create a database.
        engine = database_engine if database_engine is not None else build_engine(Settings().database_url)
        try:
            init_db(engine)
            application.state.session_factory = create_session_factory(engine)
            from app.services.sync_service import recover_interrupted
            with application.state.session_factory() as session:
                recover_interrupted(session)
            yield
        finally:
            if database_engine is None:
                engine.dispose()

    application = FastAPI(title="StudyFlow API", version="0.6.0", lifespan=lifespan)
    application.include_router(health_router)
    application.include_router(catalog_router)
    application.include_router(canvas_router)
    application.add_exception_handler(CanvasError, canvas_error_handler)
    application.include_router(document_router)
    application.add_exception_handler(DocumentError, document_error_handler)
    application.include_router(knowledge_router)
    application.include_router(sync_router)
    application.include_router(study_router)
    application.add_exception_handler(AIError, ai_error_handler)
    return application


app = create_app()
