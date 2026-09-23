"""SQLite engine, session lifecycle and explicit development initialization."""

from collections.abc import Generator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import PROJECT_ROOT


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.drivername != "sqlite":
        raise ValueError("Phase 2 supports only sqlite:/// URLs")
    memory = not url.database or url.database == ":memory:"
    if not memory:
        path = Path(url.database)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=str(path.resolve()))
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30},
        **({"poolclass": StaticPool} if memory else {}),
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    from app import models  # noqa: F401 -- register all tables before create_all

    from app.core.schema_upgrade import upgrade_sync_columns
    upgrade_sync_columns(engine)
    Base.metadata.create_all(engine)


def get_db(request: Request) -> Generator[Session, None, None]:
    # Callers own commits. Closing rolls back any uncommitted transaction.
    with request.app.state.session_factory() as session:
        yield session
