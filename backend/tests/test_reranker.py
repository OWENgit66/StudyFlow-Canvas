"""Synthetic reranker contracts: no models, downloads or private corpus."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.reranker_provider import LocalRerankerProvider, rerank_candidates
from evals.rag_retrieval import evaluate_questions


def hits():
    return [SimpleNamespace(chunk_id=i, text=f'Example {i}', score=.9-i*.1,
                            resource_id=10+i, page_number=i+1, resource_title='Synthetic.pdf',
                            course_id=1, source_link=f'/resources/{i}#page={i+1}') for i in range(5)]


def test_scores_reorder_only_candidates_and_preserve_original_metadata():
    candidates = hits()
    originals = [vars(hit).copy() for hit in candidates]
    provider = SimpleNamespace(score=Mock(return_value=[1., 3., 2., -1., 0.]))
    result = rerank_candidates('中文问题', candidates, provider)
    provider.score.assert_called_once_with('中文问题', [h.text for h in candidates])
    assert [r.chunk_id for r in result] == [1, 2, 0, 4, 3]
    for r in result:
        assert r.score == candidates[r.chunk_id].score
        assert r.source_link == candidates[r.chunk_id].source_link
        assert r.page_number == candidates[r.chunk_id].page_number
        assert r.original_rank == r.chunk_id+1
    assert [vars(hit) for hit in candidates] == originals


def test_ties_keep_original_order():
    assert [r.chunk_id for r in rerank_candidates('q', hits(), SimpleNamespace(score=lambda *a:[0]*5))] == list(range(5))


@pytest.mark.parametrize('scores', [[1], [1, 2, 3, 4, float('nan')], [1, 2, 3, 4, float('inf')],
                                    [1, 2, 3, 4, True], [1, 2, 3, 4, '5']])
def test_invalid_scores_fail_without_silent_fallback(scores):
    with pytest.raises(ValueError, match='Invalid reranker'):
        rerank_candidates('q', hits(), SimpleNamespace(score=lambda *a:scores))


def test_empty_oversized_and_duplicate_candidates():
    provider = SimpleNamespace(score=Mock(side_effect=AssertionError('Must not infer')))
    assert rerank_candidates('q', [], provider) == []
    with pytest.raises(ValueError):
        rerank_candidates('q', hits()*3, provider)
    with pytest.raises(ValueError, match='Duplicate'):
        rerank_candidates('q', hits()*2, provider)
    with pytest.raises(ValueError):
        rerank_candidates(' ', hits(), provider)
    provider.score.assert_not_called()


def test_top5_set_preserved_but_top3_regression_is_visible():
    candidates = hits()
    gold = [{'question':'q','course_id':1,'expected_resource_id':10,'expected_pages':[1]}]
    before = evaluate_questions(gold, lambda *a,**kw:candidates)
    ranked = rerank_candidates('q', candidates, SimpleNamespace(score=lambda *a:[0,1,2,3,4]))
    after = evaluate_questions(gold, lambda *a,**kw:ranked)
    assert before['evidence_hits'] == {1:1, 3:1, 5:1}
    assert after['evidence_hits'] == {1:0, 3:0, 5:1}
    assert before['hits'][5] == after['hits'][5]


def test_provider_uses_pairs_in_input_order_and_small_batch():
    provider = LocalRerankerProvider.__new__(LocalRerankerProvider)
    provider.encoder = SimpleNamespace(rerank=Mock(return_value=iter([-.5, .75])))
    assert provider.score('中文问题', ['English passage one', 'English passage two']) == [-.5, .75]
    provider.encoder.rerank.assert_called_once_with('中文问题', ['English passage one', 'English passage two'], batch_size=1)


def test_eval_runner_preserves_frozen_index_and_saves_both_scores(tmp_path, engine, db, graph, monkeypatch):
    import json
    import sqlite3
    from app.models import DocumentChunk
    from app.models.common import ResourceStatus
    from app.services.retrieval_service import RetrievalService
    from evals import rerank_eval
    from evals.retrieval_ab import file_hash, snapshot_digest

    _, course, _, resource = graph
    resource.sync_status = ResourceStatus.parsed
    db.add_all([DocumentChunk(resource_id=resource.id, page_number=i+1, chunk_index=i,
                              content=f'Synthetic body {i}') for i in range(5)])
    db.commit()
    provider = SimpleNamespace(model='synthetic', model_version='1', dimensions=2,
                               embed=lambda texts:[[1., 0.] for _ in texts], embed_query=lambda q:[1., 0.])
    service = RetrievalService(provider)
    service.index_course(db, course.id)
    found = service.search(db, course.id, 'q', top_k=5)
    db.rollback()
    previous = tmp_path/'previous'
    previous.mkdir()
    index = previous/'B.sqlite'
    raw = engine.raw_connection()
    with sqlite3.connect(index) as destination:
        raw.driver_connection.backup(destination)
    raw.close()
    gold = tmp_path/'gold.json'
    rows = [{'sample_id':'test', 'question':'q','course_id':course.id,
             'expected_resource_id':resource.id,'expected_pages':[5]}]
    gold.write_text(json.dumps(rows))
    baseline = evaluate_questions(rows,lambda *a,**kw:found)
    metadata = {'profiles':{'B':{'course_id':course.id,'index_file':index.name,
                                'model':'synthetic','model_version':'1',
                                'source_rows_sha256':snapshot_digest(index),
                                'index_rows_sha256':snapshot_digest(index,embeddings=True)}},
                'gold_sha256':file_hash(gold),'protected_code_sha256':{},'results':{'B':baseline}}
    (previous/'comparison.json').write_text(json.dumps(metadata))
    monkeypatch.setattr(rerank_eval,'LocalEmbeddingProvider',lambda **kw:provider)
    reranker = SimpleNamespace(model='fake',model_version='1',max_tokens=512,
                               score=Mock(return_value=[0.,1.,2.,3.,4.]),is_truncated=lambda *a:False)
    monkeypatch.setattr(rerank_eval,'LocalRerankerProvider',lambda **kw:reranker)
    original_hash = file_hash(index)
    output = tmp_path/'result'
    result = rerank_eval.run(previous,gold,output)
    assert result['before']['evidence_hits'][1] == 0
    assert result['after']['evidence_hits'][1] == 1
    assert result['candidate_pairs'] == 5
    top = result['after']['results'][0]['top_5'][0]
    assert top['rerank_score'] == 4 and top['original_similarity_score'] == 1
    assert top['original_rank'] == 5
    reranker.score.assert_called_once()
    assert file_hash(index) == original_hash
    with pytest.raises(FileExistsError):
        rerank_eval.run(previous,gold,output)
