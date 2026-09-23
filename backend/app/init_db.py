"""Run with python -m app.init_db from the backend directory."""

from app.core.config import Settings
from app.core.database import Base, build_engine, init_db


def main() -> None:
    engine = build_engine(Settings().database_url)
    try:
        init_db(engine)
        print("Database initialized; tables:", ", ".join(sorted(Base.metadata.tables)))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
