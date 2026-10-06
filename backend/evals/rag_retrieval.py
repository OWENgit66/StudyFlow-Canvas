"""Explicit single-course local semantic retrieval; never generate an answer."""
import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.config import PROJECT_ROOT, Settings
from app.core.database import build_engine, create_session_factory
from app.models import ChunkEmbedding, DocumentChunk, Resource, Week
from app.services.embedding_provider import DEFAULT_CACHE, DEFAULT_MODEL, LocalEmbeddingProvider
from app.services.retrieval_service import RetrievalService, course_stats


def load_questions(path, course_id):
    rows = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(rows, list):
        raise ValueError('Retrieval gold must be a JSON array.')
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('question'), str)
                or not row['question'].strip() or len(row['question']) > 4000
                or type(row.get('course_id')) is not int or row['course_id'] != course_id
                or type(row.get('expected_resource_id')) is not int or row['expected_resource_id'] <= 0):
            raise ValueError('Each question needs text, the selected course_id and a positive expected_resource_id.')
        pages = row.get('expected_pages')
        if pages is not None and (not isinstance(pages, list)
                or any(type(page) is not int or page <= 0 for page in pages)
                or len(set(pages)) != len(pages)):
            raise ValueError('expected_pages must be null or a list of unique positive page numbers.')
    return rows


def validate_gold_sources(db, rows, course_id):
    """Validate existing source metadata without parsing or changing the corpus."""
    for row in rows:
        resource = db.get(Resource, row['expected_resource_id'])
        week = db.get(Week, resource.week_id) if resource else None
        if week is None or week.course_id != course_id:
            raise ValueError('Expected resource is missing or belongs to another course.')
        pages = row.get('expected_pages') or []
        if pages:
            available = set(db.scalars(select(DocumentChunk.page_number).where(
                DocumentChunk.resource_id == resource.id)))
            if not set(pages).issubset(available):
                raise ValueError('Expected page is missing from the resource DocumentChunks.')


def evaluate_questions(rows, retrieve):
    hits = {k: 0 for k in (1, 3, 5)}
    evidence_hits = {k: 0 for k in hits}
    evidence_questions = 0
    results = []
    for row in rows:
        found = retrieve(row['course_id'], row['question'], top_k=5)
        resources = [result.resource_id for result in found]
        pages = row.get('expected_pages') or []
        evidence_at = None
        # Rank is chunk rank, not deduplicated resource rank.
        for k in hits:
            hits[k] += row['expected_resource_id'] in resources[:k]
        if pages:
            evidence_questions += 1
            evidence_at = {k: any(result.resource_id == row['expected_resource_id']
                                 and result.page_number in pages for result in found[:k])
                           for k in hits}
            for k in hits:
                evidence_hits[k] += evidence_at[k]
        top_5 = [{'rank': rank, 'chunk_id': getattr(hit, 'chunk_id', None),
                  'score': getattr(hit, 'score', None), 'resource_id': hit.resource_id,
                  'resource_title': getattr(hit, 'resource_title', None),
                  'page_number': getattr(hit, 'page_number', None),
                  'text_preview': getattr(hit, 'text', '')[:300]}
                 for rank, hit in enumerate(found[:5], 1)]
        results.append({**row, 'retrieved_resource_ids': resources,
                        'evidence_status': 'resolved' if pages else 'unresolved',
                        'evidence_hit_at': evidence_at, 'top_5': top_5})
    return {'questions': len(rows), 'hits': hits,
            'evidence_questions': evidence_questions,
            'evidence_unresolved': len(rows) - evidence_questions,
            'evidence_hits': evidence_hits, 'results': results}


def print_report(report):
    print(f"Questions: {report['questions']}")
    print(f"Evidence resolved: {report['evidence_questions']}; unresolved: {report['evidence_unresolved']}")
    for label, counts, total in [('Resource', report['hits'], report['questions']),
                                  ('Evidence', report['evidence_hits'], report['evidence_questions'])]:
        for k, correct in counts.items():
            accuracy = f'{correct/total:.2%}' if total else 'N/A'
            print(f'{label} Hit@{k}: {correct}/{total} ({accuracy})')
    for row in report['results']:
        if row['evidence_hit_at'] is None or row['evidence_hit_at'][5]:
            continue
        print(f"\n[Evidence Hit@5 FAIL] {row.get('sample_id', '')}\nQuestion: {row['question']}")
        print(f"Expected Resource: {row['expected_resource_id']}\nExpected Pages: {row['expected_pages']}")
        print('Top-5:')
        for hit in row['top_5']:
            print(f"{hit['rank']}. score={hit['score']} resource_id={hit['resource_id']} "
                  f"title={hit['resource_title']} page={hit['page_number']} chunk_id={hit['chunk_id']}")
            print(f"Text preview: {hit['text_preview']}")


def existing_engine():
    url = make_url(Settings().database_url)
    path = Path(url.database or '')
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if url.drivername != 'sqlite' or not path.is_file():
        raise ValueError('Configure an existing SQLite database; this CLI does not create a corpus.')
    return build_engine(str(url))


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')  # PDF symbols survive Windows redirection.
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('stats', 'prepare-model', 'index', 'search', 'eval'):
        command = commands.add_parser(name)
        if name != 'prepare-model':
            command.add_argument('--course-id', type=int, required=True)
        if name != 'stats':
            command.add_argument('--model-cache', type=Path, default=DEFAULT_CACHE)
        if name == 'search':
            command.add_argument('--query', required=True)
            command.add_argument('--top-k', type=int, default=5)
            command.add_argument('--resource-type', action='append', choices=('lecture', 'tutorial', 'other'))
        if name == 'eval':
            command.add_argument('--dataset', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'eval':
            rows = load_questions(args.dataset, args.course_id)
            if not rows:
                print('No retrieval eval questions available.')
                print_report(evaluate_questions([], None))
                return 0
        if args.command == 'prepare-model':
            provider = LocalEmbeddingProvider(cache_dir=args.model_cache, allow_download=True)
            print(f'Local model ready: {provider.model}; version: {provider.model_version}')
            return 0
        if args.course_id <= 0:
            raise ValueError('course_id must be positive.')
        engine = existing_engine()
        try:
            with create_session_factory(engine)() as db:
                print(json.dumps(course_stats(db, args.course_id), ensure_ascii=False))
                if args.command == 'stats':
                    return 0
                if args.command == 'eval':
                    validate_gold_sources(db, rows, args.course_id)
                db.rollback()
                if args.command == 'index':
                    # Add only this new table. No corpus migration or application startup.
                    ChunkEmbedding.__table__.create(engine, checkfirst=True)
                else:
                    from sqlalchemy import inspect
                    if not inspect(engine).has_table('chunk_embeddings'):
                        raise ValueError('No embedding index; run the explicit index command first.')
                service = RetrievalService(LocalEmbeddingProvider(cache_dir=args.model_cache))
                if args.command == 'index':
                    print(json.dumps(service.index_course(db, args.course_id)))
                elif args.command == 'search':
                    found = service.search(db, args.course_id, args.query, top_k=args.top_k,
                                           resource_types=args.resource_type)
                    print('Query: ' + args.query)
                    print(json.dumps([hit.to_dict() for hit in found], ensure_ascii=False, indent=2))
                    if not found:
                        print('No current indexed chunks match this course/filter. No answer generated.')
                else:
                    report = evaluate_questions(rows, lambda course, query, **kwargs:
                                                service.search(db, course, query, **kwargs))
                    print_report(report)
                    print(json.dumps(report['results'], ensure_ascii=False, indent=2))
        finally:
            engine.dispose()
    except (ValueError, OSError, ImportError):
        # Do not echo provider exceptions, local config or course content on failure.
        parser.exit(2, 'Retrieval could not run. Check course/dataset, existing database, optional dependencies '
                       'and prepared model cache. No paid provider fallback is used.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
