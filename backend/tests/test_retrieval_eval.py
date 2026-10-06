"""Evidence evaluation uses synthetic sources; no model, PDF, or remote API."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.models import DocumentChunk
from evals.rag_retrieval import (
    evaluate_questions, load_questions, print_report, validate_gold_sources,
)


def question(**overrides):
    return {'sample_id': 'example', 'question': 'Explain the topic', 'course_id': 1,
            'expected_resource_id': 10, 'expected_pages': [2, 3], **overrides}


def hit(resource=10, page=2):
    return SimpleNamespace(resource_id=resource, page_number=page, chunk_id=123,
                           score=0.75, resource_title='Synthetic.pdf', text='Synthetic evidence')


def test_resource_hit_does_not_imply_evidence_hit(capsys):
    report = evaluate_questions([question()], lambda *a, **k: [hit(page=1), hit(resource=20)])
    assert report['hits'] == {1: 1, 3: 1, 5: 1}
    assert report['evidence_hits'] == {1: 0, 3: 0, 5: 0}
    print_report(report)
    out = capsys.readouterr().out
    for text in ['[Evidence Hit@5 FAIL] example', 'Explain the topic', 'Expected Resource: 10',
                 'Expected Pages: [2, 3]', '1. score=0.75 resource_id=10',
                 'Synthetic.pdf page=1 chunk_id=123', 'Text preview: Synthetic evidence']:
        assert text in out


def test_same_page_from_other_resource_is_not_evidence():
    report = evaluate_questions([question()], lambda *a, **k: [hit(resource=20)])
    assert report['evidence_hits'] == {1: 0, 3: 0, 5: 0}


@pytest.mark.parametrize('page', [2, 3])
def test_any_labeled_page_counts_without_deduplicating_resource_rank(page):
    retrieve = Mock(return_value=[hit(page=1), hit(page=1), hit(page=1), hit(page=page)])
    report = evaluate_questions([question()], retrieve)
    retrieve.assert_called_once_with(1, 'Explain the topic', top_k=5)
    assert report['evidence_hits'] == {1: 0, 3: 0, 5: 1}
    assert report['results'][0]['retrieved_resource_ids'] == [10, 10, 10, 10]


def test_unresolved_excluded_from_evidence_denominator_but_keeps_resource_metric(capsys):
    legacy = question()
    del legacy['expected_pages']
    rows = [question(), question(expected_pages=[]), question(expected_pages=None), legacy]
    report = evaluate_questions(rows, lambda *a, **k: [hit()])
    assert report['questions'] == 4 and report['hits'][1] == 4
    assert report['evidence_questions'] == 1 and report['evidence_unresolved'] == 3
    assert report['evidence_hits'][1] == 1
    assert report['results'][1]['evidence_hit_at'] is None
    print_report(report)
    out = capsys.readouterr().out
    assert 'Resource Hit@1: 4/4 (100.00%)' in out
    assert 'Evidence Hit@1: 1/1 (100.00%)' in out
    assert 'FAIL' not in out


def test_no_evidence_labels_reports_na(capsys):
    report = evaluate_questions([question(expected_pages=[])], lambda *a, **k: [])
    print_report(report)
    assert 'Evidence Hit@5: 0/0 (N/A)' in capsys.readouterr().out


def test_missing_page_is_a_miss_and_preview_is_bounded():
    found = hit(page=None)
    found.text = 'x' * 1000
    report = evaluate_questions([question()], lambda *a, **k: [found])
    assert report['evidence_hits'][5] == 0
    assert len(report['results'][0]['top_5'][0]['text_preview']) == 300


@pytest.mark.parametrize('pages', [[0], [-1], [True], ['2'], [2.0], '2', {}, [2, 2], [[2]]])
def test_invalid_expected_pages(tmp_path, pages):
    path = tmp_path / 'questions.json'
    path.write_text(json.dumps([question(expected_pages=pages)]))
    with pytest.raises(ValueError, match='expected_pages'):
        load_questions(path, 1)


@pytest.mark.parametrize('pages', [None, [], [2], [3, 2]])
def test_optional_page_schema(tmp_path, pages):
    path = tmp_path / 'questions.json'
    rows = [question(expected_pages=pages)]
    path.write_text(json.dumps(rows))
    assert load_questions(path, 1) == rows


def test_expected_pages_validated_against_selected_resource(db, graph):
    _, course, _, resource = graph
    db.add(DocumentChunk(resource_id=resource.id, page_number=2, chunk_index=0, content='Synthetic'))
    db.commit()
    row = question(course_id=course.id, expected_resource_id=resource.id, expected_pages=[2])
    validate_gold_sources(db, [row], course.id)
    with pytest.raises(ValueError, match='Expected page'):
        validate_gold_sources(db, [{**row, 'expected_pages': [3]}], course.id)
    with pytest.raises(ValueError, match='another course'):
        validate_gold_sources(db, [row], course.id + 1)
    with pytest.raises(ValueError, match='missing'):
        validate_gold_sources(db, [{**row, 'expected_resource_id': resource.id + 100}], course.id)
