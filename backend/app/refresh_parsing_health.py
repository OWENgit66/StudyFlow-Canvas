"""Backfill compact reports for local active-semester PDFs only. No chunk/AI changes."""
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import build_engine, create_session_factory, init_db
from app.models import Resource, Week, Course, Semester, SyncRecord
from app.schemas.parsing_health import ParsingHealth
from app.services.document_service import DocumentService
from app.services.document_errors import DocumentError
from app.services.material_paths import resolve_database_path
from app.services.parsing_health import source_fingerprint, build_report, store_report


def refresh(db, documents):
    if db.scalar(select(SyncRecord.id).where(SyncRecord.status == 'running')):
        raise ValueError('Wait until the active sync stops before refreshing reports.')
    counts = {'reviewed': 0, 'healthy': 0, 'needs_review': 0, 'unable_to_parse': 0, 'unavailable': 0}
    resources = db.scalars(select(Resource).join(Week).join(Course).join(Semester)
        .where(Semester.is_active.is_(True))).all()
    for resource in resources:
        if resource.file_type.lower() not in {'pdf', '.pdf', 'application/pdf'}:
            continue
        fingerprint = source_fingerprint(resource, documents.root)
        if fingerprint is None:
            counts['unavailable'] += 1
            continue
        try:
            document = documents.parse(resolve_database_path(resource.local_path), resource.id, resource.file_type)
            report = build_report(document)
        except DocumentError:
            report = ParsingHealth(status='unable_to_parse')
        if fingerprint != source_fingerprint(resource, documents.root):
            counts['unavailable'] += 1
            continue  # Never attach old warnings to a changed source.
        store_report(resource, fingerprint, report)
        counts['reviewed'] += 1
        counts['needs_review' if report.status == 'review' else report.status] += 1
        db.commit()
    return counts


def main():
    settings = Settings()
    engine = build_engine(settings.database_url)
    try:
        init_db(engine)
        with create_session_factory(engine)() as db:
            print(refresh(db, DocumentService(settings)))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
