"""RAG V1 CLI: local evidence preview by default; --generate explicitly enables paid LLM use."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings
from app.services.ai_errors import AIError
from app.services.embedding_provider import LocalEmbeddingProvider
from app.services.llm_factory import create_llm_provider
from app.services.rag_answer_service import RAGAnswerService, SYSTEM_PROMPT
from app.services.reranker_provider import LocalRerankerProvider
from app.services.retrieval_service import RetrievalService
from evals.rag_retrieval import load_questions
from evals.retrieval_ab import snapshot_digest, file_hash

EXPERIMENT_ROOT = PROJECT_ROOT / 'data/retrieval-eval'


def load_runtime(previous_dir, policy_path, course_id):
    """Use the existing multilingual snapshot read-only; never create embeddings."""
    previous_dir = Path(previous_dir).resolve()
    previous = json.loads((previous_dir / 'comparison.json').read_text('utf-8'))
    profile = previous['profiles']['B']
    policy = json.loads(Path(policy_path).read_text('utf-8'))
    index = (previous_dir / profile['index_file']).resolve()
    if index.parent != previous_dir or profile['course_id'] != course_id or policy['candidates'] != 5:
        raise ValueError('Require the frozen course index and five-candidate policy.')
    if (snapshot_digest(index) != profile['source_rows_sha256']
            or snapshot_digest(index, embeddings=True) != profile['index_rows_sha256']):
        raise ValueError('Frozen corpus/index changed.')
    for name, sha in {**previous['protected_code_sha256'], **policy['code_sha256']}.items():
        if file_hash(PROJECT_ROOT / name) != sha:
            raise ValueError('Frozen retrieval code changed.')
    embedding = LocalEmbeddingProvider(model=profile['model'], allow_download=False)
    reranker = LocalRerankerProvider(allow_download=False)
    if (embedding.model_version != profile['model_version']
            or reranker.model != policy['reranker'] or reranker.model_version != policy['version']):
        raise ValueError('Frozen model version changed.')
    engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(index.as_uri() + '?mode=ro', uri=True))
    return engine, RAGAnswerService(RetrievalService(embedding), reranker)


def review_template(dataset, course_id):
    """Reuse question identities/Gold without generation or automated judging."""
    return [{'sample_id': row.get('sample_id'), 'question': row['question'],
             'course_id': row['course_id'], 'expected_resource_id': row['expected_resource_id'],
             'expected_pages': row.get('expected_pages'), 'answer': None, 'sources': [],
             'answerable': None, 'citation_correct': None, 'grounded': None, 'notes': ''}
            for row in load_questions(dataset, course_id)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-id', type=int, required=True)
    parser.add_argument('--question')
    parser.add_argument('--week-id', type=int)
    parser.add_argument('--resource-type', choices=['lecture', 'tutorial', 'other'])
    parser.add_argument('--top-k', type=int, choices=[1, 2, 3], default=3)
    parser.add_argument('--generate', action='store_true', help='Send one request to the configured paid LLM provider.')
    parser.add_argument('--debug', action='store_true', help='Print private evidence locally.')
    parser.add_argument('--previous-dir', type=Path, default=EXPERIMENT_ROOT / 'rag-v0.3-multilingual')
    parser.add_argument('--policy', type=Path, default=EXPERIMENT_ROOT / 'rag-v0.4-reranker/policy-before-run.json')
    parser.add_argument('--dataset', type=Path, default=EXPERIMENT_ROOT / 'questions.json')
    parser.add_argument('--review-template', type=Path, help='Write pending human review records; makes no model calls.')
    args = parser.parse_args(argv)
    if args.review_template:
        if args.generate or args.question:
            parser.error('Review template cannot be combined with generation or a question.')
        rows = review_template(args.dataset, args.course_id)
        with args.review_template.open('x', encoding='utf-8') as out:
            json.dump(rows, out, ensure_ascii=False, indent=2)
        print(f'Pending human reviews: {len(rows)}; no model calls.')
        return 0
    if not args.question or not args.question.strip():
        parser.error('--question is required for an answer/preview.')
    settings = Settings()
    print(f'Provider: {settings.llm_provider}; Model: {settings.llm_model}')
    print('Paid provider: yes (when --generate is used); maximum requests: 1; automatic retries: 0')
    engine, service = load_runtime(args.previous_dir, args.policy, args.course_id)
    try:
        with Session(engine) as db:
            evidence = service.prepare(db, args.course_id, args.question, week_id=args.week_id,
                                       resource_type=args.resource_type, top_k=args.top_k)
        payload = service.context(args.question, evidence)
        print(f'Evidence chunks: {len(evidence)}; context JSON characters: {len(payload)}; '
              f'system characters: {len(SYSTEM_PROMPT)} (schema also sent; token usage unknown until response)')
        if args.debug:
            print(payload)
        if not args.generate:
            print('Preview only. No LLM API call made. Use --generate only after reviewing cost/scope.')
            return 0
        if evidence:
            service.provider = create_llm_provider(settings)
        answer = service.generate(args.question, evidence)
        print('Question:', args.question)
        print('Answer:', answer.answer)
        print('Sources:')
        for source in answer.sources:
            print(f'[{source.citation_id}] {source.week} — {source.title}, p.{source.page}; '
                  f'R{source.resource_id}; {source.resource_type}; {source.source_url or ""}')
        return 0
    finally:
        engine.dispose()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except AIError as error:
        print(f'Answer generation failed ({error.code}); no answer returned.', file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, OSError, RuntimeError, KeyError):
        print('Answer prototype failed: check local frozen index, model cache, inputs and output path.', file=sys.stderr)
        raise SystemExit(1) from None
