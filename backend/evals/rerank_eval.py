"""V0.4: rerank exactly five frozen multilingual candidates, never generate answers."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.services.embedding_provider import LocalEmbeddingProvider
from app.services.retrieval_service import RetrievalService
from app.services.reranker_provider import LocalRerankerProvider, rerank_candidates
from evals.rag_retrieval import load_questions, validate_gold_sources, evaluate_questions, print_report
from evals.retrieval_ab import file_hash, snapshot_digest, compare_reports


def run(previous_dir, dataset, output_dir):
    previous_dir, dataset, out = Path(previous_dir).resolve(), Path(dataset).resolve(), Path(output_dir).resolve()
    previous = json.loads((previous_dir/'comparison.json').read_text('utf-8'))
    profile = previous['profiles']['B']
    course_id = profile['course_id']
    index = (previous_dir/profile['index_file']).resolve()
    if index.parent != previous_dir:
        raise ValueError('Index must be inside the frozen experiment directory.')
    if file_hash(dataset) != previous['gold_sha256']:
        raise ValueError('Gold differs from frozen V0.3.')
    rows = load_questions(dataset, course_id)
    if snapshot_digest(index) != profile['source_rows_sha256'] or snapshot_digest(index, embeddings=True) != profile['index_rows_sha256']:
        raise ValueError('Frozen corpus/index changed.')
    for name, sha in previous['protected_code_sha256'].items():
        if file_hash(PROJECT_ROOT/name) != sha:
            raise ValueError('Retriever, embedding, hygiene or Eval changed.')
    out.mkdir(parents=True, exist_ok=False)
    before_hashes = {str(p):file_hash(p) for p in previous_dir.iterdir() if p.is_file()}
    before_hashes[str(dataset)] = file_hash(dataset)
    provider = LocalEmbeddingProvider(model=profile['model'], allow_download=False)
    if provider.model_version != profile['model_version']:
        raise ValueError('Embedding model version changed.')
    reranker = LocalRerankerProvider(allow_download=False)
    policy = {'reranker':reranker.model, 'version':reranker.model_version, 'max_pair_tokens':reranker.max_tokens,
              'candidates':5, 'tie_break':'original retrieval rank', 'scores':'raw logits, separate from cosine',
              'code_sha256':{name:file_hash(PROJECT_ROOT/name) for name in
                ['backend/app/services/reranker_provider.py','backend/evals/rerank_eval.py']}}
    (out/'policy-before-run.json').write_text(json.dumps(policy,indent=2),encoding='utf-8')
    service = RetrievalService(provider)
    engine = create_engine('sqlite://', creator=lambda:sqlite3.connect(index.as_uri()+'?mode=ro',uri=True))
    found_by_query, reranked_by_query, truncated = {}, {}, {}
    started = time.monotonic()
    expected = {r['question']:r for r in previous['results']['B']['results']}
    try:
        with Session(engine) as db:
            validate_gold_sources(db, rows, course_id)
            for row in rows:
                query = row['question']
                found = service.search(db, course_id, query, top_k=5)
                old = expected[query]['top_5']
                if len(found) != 5 or any(h.chunk_id != saved['chunk_id'] or abs(h.score-saved['score'])>1e-12
                                         for h,saved in zip(found,old)):
                    raise ValueError('Multilingual candidates differ from frozen V0.3.')
                found_by_query[query] = found
                truncated[query] = {h.chunk_id:reranker.is_truncated(query,h.text) for h in found}
                reranked_by_query[query] = rerank_candidates(query, found, reranker)
                print(f"Scored {row.get('sample_id', '')}: 5 candidates", flush=True)
    finally:
        engine.dispose()
    before = evaluate_questions(rows, lambda course,query,**kw:found_by_query[query])
    after = evaluate_questions(rows, lambda course,query,**kw:reranked_by_query[query])
    for report, hits in [(before,found_by_query),(after,reranked_by_query)]:
        for row in report['results']:
            score_by_id = {h.chunk_id:h for h in reranked_by_query[row['question']]}
            for item in row['top_5']:
                h = score_by_id[item['chunk_id']]
                item.update({'original_similarity_score':h.score, 'rerank_score':h.rerank_score,
                             'original_rank':h.original_rank,
                             'reranker_input_truncated':truncated[row['question']][h.chunk_id]})
    if before['hits'][5] != after['hits'][5] or before['evidence_hits'][5] != after['evidence_hits'][5]:
        raise ValueError('Reranking unexpectedly changed the candidate set.')
    for name, sha in before_hashes.items():
        if file_hash(name) != sha:
            raise ValueError('Frozen experiment/Gold modified.')
    result = {'experiment':'RAG V0.4 Local Reranker', 'policy':policy,
              'before':before, 'after':after, 'changes':compare_reports(before,after),
              'candidate_pairs':len(rows)*5, 'local_query_embeddings':len(rows),
              'document_embeddings':0, 'paid_api_calls':0, 'seconds':time.monotonic()-started,
              'truncated_pairs':sum(sum(flags.values()) for flags in truncated.values()),
              'frozen_input_sha256':before_hashes}
    (out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Before'); print_report(before)
    print('After'); print_report(after)
    return result


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-dir',type=Path,required=True)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    run(args.previous_dir,args.dataset,args.output_dir)


if __name__=='__main__':
    main()
