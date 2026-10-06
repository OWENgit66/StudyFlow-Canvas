"""Isolated model A/B experiment using unchanged production retrieval and Eval.

Each model/version owns a separate SQLite experiment file. The live database
and its embeddings are read-only; no migrations or production defaults change.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

from sqlalchemy.engine import make_url

from app.core.config import PROJECT_ROOT, Settings
from app.core.database import Base, build_engine, create_session_factory
from app.models import Semester, Course, Week, Resource, DocumentChunk, ChunkEmbedding
from app.services.embedding_provider import DEFAULT_MODEL, LocalEmbeddingProvider
from app.services.retrieval_service import RetrievalService
from evals.rag_retrieval import load_questions, validate_gold_sources, evaluate_questions, print_report

MULTILINGUAL_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
TABLES = [Semester, Course, Week, Resource, DocumentChunk, ChunkEmbedding]


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create_course_snapshot(source, destination, course_id, *, include_embeddings):
    """Copy exactly one course's source rows, with an optional existing index."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if type(course_id) is not int or course_id <= 0 or source == destination:
        raise ValueError('Require a positive course and a distinct new snapshot path.')
    # No truncating/reusing a previous experiment or the main database.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
        src.execute('BEGIN')
        if not src.execute('SELECT 1 FROM courses WHERE id=?', (course_id,)).fetchone():
            raise ValueError('Course not found.')
        with destination.open('xb'):
            pass
        engine = build_engine('sqlite:///' + destination.as_posix())
        try:
            Base.metadata.create_all(engine, tables=[model.__table__ for model in TABLES])
        finally:
            engine.dispose()
        predicates = {
            'semesters': 'id IN (SELECT semester_id FROM courses WHERE id=?)',
            'courses': 'id=?',
            'weeks': 'course_id=?',
            'resources': 'week_id IN (SELECT id FROM weeks WHERE course_id=?)',
            'document_chunks': 'resource_id IN (SELECT r.id FROM resources r JOIN weeks w ON r.week_id=w.id WHERE w.course_id=?)',
            'chunk_embeddings': 'chunk_id IN (SELECT d.id FROM document_chunks d JOIN resources r ON d.resource_id=r.id JOIN weeks w ON r.week_id=w.id WHERE w.course_id=?)',
        }
        counts = {}
        with sqlite3.connect(destination) as dst:
            dst.execute('PRAGMA foreign_keys=ON')
            for model in TABLES:
                name = model.__tablename__
                if name == 'chunk_embeddings' and not include_embeddings:
                    counts[name] = 0
                    continue
                columns = [r[1] for r in dst.execute(f'PRAGMA table_info({name})')]
                fields = ','.join('"'+column+'"' for column in columns)
                rows = src.execute(f'SELECT {fields} FROM {name} WHERE {predicates[name]}', (course_id,)).fetchall()
                dst.executemany(f'INSERT INTO {name} ({fields}) VALUES ({",".join("?" for _ in columns)})', rows)
                counts[name] = len(rows)
            if dst.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Snapshot foreign key check failed.')
    return counts


def snapshot_digest(path, *, embeddings=False):
    """Stable row digest excluding physical SQLite layout and index writes."""
    names = ['chunk_embeddings'] if embeddings else [m.__tablename__ for m in TABLES[:-1]]
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) as db:
        rows = {name: db.execute(f'SELECT * FROM {name} ORDER BY 1').fetchall() for name in names}
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def compare_reports(a, b):
    if [(r['question'], r['course_id'], r['expected_resource_id'], r.get('expected_pages')) for r in a['results']] != [
            (r['question'], r['course_id'], r['expected_resource_id'], r.get('expected_pages')) for r in b['results']]:
        raise ValueError('A/B Gold must be identical.')
    changes = []
    for old, new in zip(a['results'], b['results']):
        for kind in ('resource', 'evidence'):
            for k in (1, 3, 5):
                if kind == 'resource':
                    before = old['expected_resource_id'] in old['retrieved_resource_ids'][:k]
                    after = new['expected_resource_id'] in new['retrieved_resource_ids'][:k]
                else:
                    if old['evidence_hit_at'] is None:
                        continue
                    before, after = old['evidence_hit_at'][k], new['evidence_hit_at'][k]
                if before != after:
                    changes.append({'sample_id': old.get('sample_id'), 'question': old['question'],
                                    'metric': f'{kind}_hit_at_{k}', 'before': before, 'after': after,
                                    'regression': bool(before and not after)})
    return changes


def run(source, dataset, output_dir, course_id):
    rows = load_questions(dataset, course_id)
    if not rows:
        raise ValueError('A/B requires labeled questions.')
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_hash, gold_hash = file_hash(source), file_hash(dataset)
    protected = [PROJECT_ROOT/'backend/app/services'/name for name in
                 ('embedding_provider.py', 'retrieval_service.py', 'retrieval_hygiene.py', 'document_chunking.py')]
    protected.append(PROJECT_ROOT/'backend/evals/rag_retrieval.py')
    code_hashes = {str(p.relative_to(PROJECT_ROOT)): file_hash(p) for p in protected}
    profiles, reports, times = {}, {}, {}
    snapshot_a = None
    for arm, model in [('A', DEFAULT_MODEL), ('B', MULTILINGUAL_MODEL)]:
        started = time.monotonic()
        provider = LocalEmbeddingProvider(model=model, allow_download=False)
        name = hashlib.sha256(f'{model}:{provider.model_version}'.encode()).hexdigest()[:16]
        path = out / f'{arm}-{name}.sqlite'
        counts = create_course_snapshot(source if arm == 'A' else snapshot_a, path, course_id,
                                        include_embeddings=arm == 'A')
        if arm == 'A':
            snapshot_a = path
            old_index_hash = snapshot_digest(path, embeddings=True)
            if counts['chunk_embeddings'] != counts['document_chunks']:
                raise ValueError('A requires a complete existing index; no automatic regeneration.')
        elif snapshot_digest(path) != snapshot_digest(snapshot_a):
            raise ValueError('A/B source snapshots differ.')
        profiles[arm] = {'model': model, 'model_version': provider.model_version, 'dimensions': provider.dimensions,
                         'window_tokens': provider.window_tokens, 'index_file': path.name,
                         'course_id': course_id, 'snapshot_counts': counts, 'query_embeddings': 0,
                         'document_embeddings': 0, 'source_rows_sha256': snapshot_digest(path)}
        # Publish model/version identity before inference; no ambiguous index files.
        (out/f'{arm}-profile.json').write_text(json.dumps(profiles[arm], indent=2), encoding='utf-8')
        original_query = provider.embed_query
        def embed_query(text):
            profiles[arm]['query_embeddings'] += 1
            return original_query(text)
        provider.embed_query = embed_query
        service = RetrievalService(provider)
        engine = build_engine('sqlite:///' + path.as_posix())
        try:
            with create_session_factory(engine)() as db:
                validate_gold_sources(db, rows, course_id)
                if arm == 'B':
                    # Small batches bound RAM. Per-input embedding semantics are unchanged.
                    stats = service.index_course(db, course_id, batch_size=4)
                    profiles[arm]['document_embeddings'] = stats['generated']
                    if stats['generated'] != counts['document_chunks']:
                        raise ValueError('B did not index the complete frozen course corpus.')
                else:
                    from app.services.retrieval_service import course_chunks, current_embedding
                    for chunk, resource, _, _ in course_chunks(db, course_id):
                        if not current_embedding(db.get(ChunkEmbedding, chunk.id), chunk, resource, provider):
                            raise ValueError('A has stale embeddings; experiment stopped.')
                report = evaluate_questions(rows, lambda course, query, **kw: service.search(db, course, query, **kw))
                reports[arm] = report
        finally:
            engine.dispose()
        if snapshot_digest(path) != profiles[arm]['source_rows_sha256']:
            raise ValueError('Source changed during evaluation.')
        if snapshot_digest(snapshot_a, embeddings=True) != old_index_hash:
            raise ValueError('A embeddings changed.')
        times[arm] = time.monotonic() - started
        profiles[arm]['index_rows_sha256'] = snapshot_digest(path, embeddings=True)
        (out/f'{arm}-profile.json').write_text(json.dumps(profiles[arm], indent=2), encoding='utf-8')
        (out/f'{arm}-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Arm {arm}: {model}', flush=True)
        print_report(report)
        del service, provider
    if file_hash(source) != source_hash or file_hash(dataset) != gold_hash:
        raise ValueError('Original source/Gold changed during evaluation.')
    if any(file_hash(PROJECT_ROOT/name) != sha for name, sha in code_hashes.items()):
        raise ValueError('Frozen production code changed.')
    comparison = {'experiment': 'RAG V0.3 Multilingual Embedding A/B', 'profiles': profiles,
                  'gold_sha256': gold_hash, 'live_database_sha256': source_hash,
                  'protected_code_sha256': code_hashes, 'seconds': times, 'paid_api_calls': 0,
                  'changes': compare_reports(reports['A'], reports['B']), 'results': reports}
    (out/'comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
    return comparison


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-id', type=int, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    path = Path(make_url(Settings().database_url).database)
    source = path if path.is_absolute() else PROJECT_ROOT/path
    run(source, args.dataset, args.output_dir, args.course_id)


if __name__ == '__main__':
    main()
