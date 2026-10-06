"""Classification-only preview/apply CLI. No Canvas, parsing or indexing imports."""
import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import build_engine, init_db
from app.models import Course, Resource, Week
from app.services.llm_factory import create_llm_provider
from app.services.resource_classification import ResourceClassificationService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--course-id', type=int)
    scope.add_argument('--resource-id', type=int, action='append')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--apply', action='store_true', help='Persist classification only; default is preview.')
    parser.add_argument('--llm-max-calls', type=int, choices=range(0, 4), default=0,
                        help='Explicit paid opt-in: at most 1–3 calls; default 0.')
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 1000:
        parser.error('--limit must be between 1 and 1000')
    settings = Settings()
    # Factory is lazy: high confidence/manual-only runs do not even require credentials.
    class ConfiguredProvider:
        def generate(self, system, user, schema):
            return create_llm_provider(settings).generate(system, user, schema)
    classifier = ResourceClassificationService(ConfiguredProvider() if args.llm_max_calls else None,
                                               max_llm_calls=args.llm_max_calls)
    engine = build_engine(settings.database_url)
    try:
        # The normal backend startup owns migration. Preview never migrates a database.
        if args.apply:
            init_db(engine)
        with Session(engine) as db:
            if args.course_id and db.get(Course, args.course_id) is None:
                parser.error('Course not found')
            statement = select(Resource).join(Week).where(
                Week.course_id == args.course_id if args.course_id else Resource.id.in_(args.resource_id))
            rows = db.scalars(statement.order_by(Resource.id).limit(args.limit)).all()
            for resource in rows:
                before = resource.resource_type
                result = (classifier.apply if args.apply else classifier.classify)(db, resource)
                if args.apply:
                    db.commit()
                print(f'R{resource.id}: {before.value} -> {result.resource_type.value}; '
                      f'{result.method}; confidence={result.confidence:.2f}')
            print(f'Resources: {len(rows)}; applied: {args.apply}; LLM requests: {classifier.llm_calls}')
    finally:
        engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
