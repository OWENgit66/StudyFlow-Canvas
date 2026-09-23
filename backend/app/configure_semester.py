"""Explicit local configuration; never fetch courses or start paid processing."""
import argparse

from sqlalchemy import select

from app.core.config import Settings
from app.core.database import build_engine, create_session_factory, init_db
from app.models import Semester, SyncRecord


def activate(db, semester_id: int, canvas_term_id: int):
    if canvas_term_id <= 0:
        raise ValueError('Canvas term ID must be positive.')
    if db.scalar(select(SyncRecord.id).where(SyncRecord.status == 'running')):
        raise ValueError('Wait for or cancel the running sync before changing the active semester.')
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise ValueError('Semester not found; create it before activating it.')
    for current in db.scalars(select(Semester).where(Semester.is_active.is_(True))):
        current.is_active = False
    db.flush()  # Clear the partial unique index before activating another row.
    semester.canvas_term_id, semester.is_active = canvas_term_id, True
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--semester-id', type=int, required=True)
    parser.add_argument('--canvas-term-id', type=int, required=True)
    args = parser.parse_args()
    engine = build_engine(Settings().database_url)
    init_db(engine)
    try:
        with create_session_factory(engine)() as db:
            activate(db, args.semester_id, args.canvas_term_id)
        print('Active semester and Canvas term mapping saved. No sync started.')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
