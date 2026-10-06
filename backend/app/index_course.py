"""Maintain a course's shared local index; no parsing, Canvas or paid APIs."""
import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.core.database import build_engine, init_db
from app.models import Course
from app.services.course_index import index_course, index_status
from app.services.retrieval_service import course_chunks, usable


def backfill(db):
    """Visit existing courses only; the production indexer owns all vector work."""
    courses = db.execute(select(Course.id, Course.code).order_by(Course.id)).all()
    summary = dict(courses=len(courses), ready_before=0, ready=0, newly_indexed=0,
                   stale_updated=0, unavailable=0, errors=0,
                   new_embeddings=0, updated_embeddings=0, skipped_embeddings=0,
                   removed_stale=0)
    results = []
    for course_id, code in courses:
        result = {'course_id': course_id, 'code': code}
        try:
            if not any(usable(chunk, resource) for chunk, resource, _, _ in course_chunks(db, course_id)):
                result['state'] = 'unavailable'
                summary['unavailable'] += 1
            else:
                before = index_status(db, course_id)
                summary['ready_before'] += before['state'] == 'ready'
                stats = index_course(db, course_id)
                after = index_status(db, course_id)
                if after['state'] != 'ready':
                    raise ValueError('Course is not ready after indexing.')
                result.update(state='ready', **stats)
                summary['ready'] += 1
                if stats['new_embeddings'] == stats['total_chunks'] and stats['total_chunks']:
                    summary['newly_indexed'] += 1
                elif stats['new_embeddings'] or stats['updated_embeddings']:
                    summary['stale_updated'] += 1
                for key in ('new_embeddings', 'updated_embeddings', 'skipped_embeddings', 'removed_stale'):
                    summary[key] += stats[key]
        except Exception:
            db.rollback()
            result.update(state='error', message='Course backfill failed; check its index status and local model cache.')
            summary['errors'] += 1
        finally:
            db.rollback()  # Release read transactions before moving to another course.
        results.append(result)
        print(json.dumps(result, ensure_ascii=True), flush=True)
    return {**summary, 'results': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--course-id', type=int)
    scope.add_argument('--all', action='store_true', help='Backfill all existing courses incrementally.')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args(argv)
    if args.course_id is not None and args.course_id <= 0:
        parser.error('Course ID must be positive.')
    if args.all and args.status:
        parser.error('--status requires --course-id; --all performs incremental backfill.')
    engine = build_engine(Settings().database_url)
    try:
        init_db(engine)
        with Session(engine) as db:
            result = backfill(db) if args.all else (
                index_status(db, args.course_id) if args.status else index_course(db, args.course_id))
            print(json.dumps(result, ensure_ascii=True))
        return 1 if result.get('errors', 0) else 0
    except Exception:
        print('Course indexing failed. Check course existence, local model cache and index status.')
        return 1
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
