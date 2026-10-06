"""Synthetic retrieval hygiene tests: no private material or actual model."""
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.models import ChunkEmbedding, DocumentChunk
from app.models.common import ResourceStatus
from app.services.retrieval_hygiene import low_information_reason
from app.services.retrieval_service import RetrievalService


COVER = 'DEMO1234: Example Subject\nAcademic Material\nWeek 2: Topic One\nAlex Example\nSchool of Computing'
OUTLINE = 'Syllabus\n1. Topic One     1. Topic Two\n2. Topic Three     2. Topic Four'


@pytest.mark.parametrize('text', [COVER, COVER.replace('Week 2:', 'Lecture 3:')])
def test_metadata_cover_detected(text):
    assert low_information_reason(text).startswith('title/cover-like')


@pytest.mark.parametrize('text', [OUTLINE, 'Outline\n– Topic one\n– Topic two\n– Topic three'])
def test_explicit_topic_list_detected(text):
    assert low_information_reason(text).startswith('outline-like')


@pytest.mark.parametrize('text', [
    'A protocol defines message order.',
    'MAC Address Format',  # No generic short-title exclusion.
    'x = y / z',
    'host -> router',
    'BGP\nBorder Gateway Protocol',  # Short acronym expansion is evidence.
    'Topic\n– sender\n– receiver',  # Diagram/list without explicit outline marker.
    COVER + '\nCRC detects errors',
    COVER + '\nWhat does the protocol do?',
    COVER + '\nx = 2',
    'Outline\n1. A packet contains data\n2. A router forwards packets\n3. A frame is transmitted',
    'Syllabus\n' + 'A long body explaining substantive information ' * 50,
    'Outline\nTopic one\nThis wrapped line lacks a list marker\n– Topic two',
    'Outline\n– ' + 'word ' * 11 + '\n– Topic two\n– Topic three',
    COVER.replace('School of Computing', 'An uncertain line'),
    '',
])
def test_uncertain_or_substantive_text_retained(text):
    assert low_information_reason(text) is None


class SyntheticEmbedding:
    model = 'synthetic'
    model_version = '1'
    dimensions = 2

    def embed(self, texts):
        return [[1., 0.] if text in (COVER, OUTLINE) else [.8, .6] for text in texts]

    def embed_query(self, query):
        return [1., 0.]


def test_filter_before_top_k_preserves_source_and_index(db, graph):
    _, course, _, resource = graph
    resource.sync_status = ResourceStatus.parsed
    # A cover away from page 1 and genuine body ON page 1.
    chunks = [DocumentChunk(resource_id=resource.id, page_number=page, chunk_index=i, content=text)
              for i, (page, text) in enumerate([(8, COVER), (9, OUTLINE), (1, 'A protocol defines message order.')])]
    db.add_all(chunks)
    db.commit()
    service = RetrievalService(SyntheticEmbedding())
    assert service.index_course(db, course.id)['generated'] == 3
    snapshot = [(r.chunk_id, r.embedding, r.content_hash, r.source_hash, r.generated_at)
                for r in db.scalars(select(ChunkEmbedding))]
    before_text = [(c.id, c.content) for c in chunks]
    debug = []
    found = service.search(db, course.id, 'q', top_k=1, diagnostics=debug)
    assert [r.page_number for r in found] == [1]
    assert found[0].score == pytest.approx(.8)
    assert {d['chunk_id'] for d in debug} == {chunks[0].id, chunks[1].id}
    assert all(d['low_information_reason'] for d in debug)
    assert 'low_information_reason' not in found[0].to_dict()
    assert snapshot == [(r.chunk_id, r.embedding, r.content_hash, r.source_hash, r.generated_at)
                        for r in db.scalars(select(ChunkEmbedding))]
    assert before_text == [(c.id, c.content) for c in db.scalars(select(DocumentChunk).order_by(DocumentChunk.id))]
    assert service.index_course(db, course.id)['generated'] == 0


def test_only_covers_returns_no_candidates_without_query_inference(db, graph):
    _, course, _, resource = graph
    resource.sync_status = ResourceStatus.parsed
    db.add(DocumentChunk(resource_id=resource.id, page_number=4, chunk_index=0, content=COVER))
    db.commit()
    provider = SyntheticEmbedding()
    service = RetrievalService(provider)
    service.index_course(db, course.id)
    provider.embed_query = Mock(side_effect=AssertionError('No query needed'))
    assert service.search(db, course.id, 'q') == []
    provider.embed_query.assert_not_called()


def test_debug_respects_resource_type_filter(db, graph):
    _, course, _, resource = graph
    resource.sync_status = ResourceStatus.parsed
    db.add(DocumentChunk(resource_id=resource.id, page_number=1, chunk_index=0, content=COVER))
    db.commit()
    service = RetrievalService(SyntheticEmbedding())
    service.index_course(db, course.id)
    debug = []
    assert service.search(db, course.id, 'q', resource_types=['lecture'], diagnostics=debug) == []
    assert debug == []  # Fixture defaults to other; no out-of-scope diagnostics.
