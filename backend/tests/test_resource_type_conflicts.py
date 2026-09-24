"""Metadata-only V2.2a regression tests: no sync, PDF, database or provider calls."""
import json

import pytest

from app.services.material_classification import classify_resource_type, resource_role_evidence


@pytest.mark.parametrize('context,expected', [
    ({'filename': 'Assignment1.pdf', 'module_title': 'Lectures'}, 'other'),
    ({'nearby_text': 'Before lecture Essential reading'}, 'other'),
    ({'nearby_text': 'Before lecture Recommended readings'}, 'other'),
    ({'filename': 'Week 5 Lecture.pdf', 'nearby_text': 'Essential reading'}, 'lecture'),
    ({'filename': 'Week5.pdf', 'module_title': 'Lectures'}, 'lecture'),
    ({'filename': 'Week5.pdf', 'nearby_text': 'Before lecture'}, 'lecture'),
    ({'filename': 'Week5.pdf', 'module_title': 'Tutorials'}, 'tutorial'),
    ({'filename': 'Week5.pdf', 'nearby_text': 'During tutorial'}, 'tutorial'),
    ({'filename': 'Assessment2.pdf', 'module_title': 'Lectures'}, 'other'),
    ({'filename': 'Homework.pdf', 'module_title': 'Tutorials'}, 'other'),
    ({'filename': 'Notes.pdf', 'module_title': 'Tutorials', 'page_title': 'Required readings'}, 'other'),
    ({'filename': 'Notes.pdf', 'nearby_text': 'Tutorial homework'}, 'other'),
    ({'filename': 'Tutorial Solutions.pdf', 'nearby_text': 'Recommended readings'}, 'tutorial'),
    ({'filename': 'Assignment1.pdf', 'item_title': 'Lecture example'}, 'lecture'),
    ({'filename': 'Reading.pdf', 'link_text': 'Tutorial examples'}, 'tutorial'),
    ({'filename': 'Reading.pdf', 'page_title': 'Lecture examples'}, 'lecture'),
    ({'filename': 'Homework.pdf', 'page_title': 'Tutorial examples'}, 'tutorial'),
    ({'filename': 'Notes.pdf', 'page_title': 'Tutorial', 'module_title': 'Lectures'}, 'tutorial'),
    ({'filename': 'Notes.pdf', 'page_title': 'Lecture', 'module_title': 'Tutorials'}, 'lecture'),
    ({'filename': 'Lecture.pdf', 'page_title': 'Tutorial', 'nearby_text': 'Reading'}, 'lecture'),
    ({'filename': 'Notes.pdf', 'item_title': 'Tutorial', 'page_title': 'Lecture'}, 'tutorial'),
    ({'filename': 'Lecture and Tutorial.pdf', 'nearby_text': 'Reading'}, 'other'),
    ({'filename': 'Reassignment.pdf', 'module_title': 'Lectures'}, 'lecture'),
    ({'filename': 'Proofreading.pdf', 'module_title': 'Lectures'}, 'lecture'),
    ({'filename': 'Reading.pdf'}, 'other'),
    ({'filename': 'Slides.pdf'}, 'other'),
])
def test_direct_signals_and_weak_context_conflicts(context, expected):
    assert classify_resource_type(**context) == expected


@pytest.mark.parametrize('direct_source', ['filename', 'display_name', 'item_title', 'link_text', 'page_title'])
def test_direct_role_survives_other_intent_after_duplicate_merge(direct_source):
    weak = resource_role_evidence(module_title='Lectures', nearby_text='Essential readings')
    direct = resource_role_evidence(**{direct_source: 'Tutorial'})
    for merged in (weak + direct, direct + weak):
        # Sync records JSON-serialize evidence before adding canonical file metadata.
        restored = json.loads(json.dumps(sorted(set(merged))))
        assert classify_resource_type(restored, filename='Exercises.pdf') == 'tutorial'


def test_other_intent_survives_duplicate_merge_and_canonical_metadata():
    weak = resource_role_evidence(module_title='Lectures')
    intent = resource_role_evidence(item_title='Assignment1')
    for merged in (weak + intent, intent + weak):
        restored = json.loads(json.dumps(sorted(set(merged))))
        assert classify_resource_type(restored, filename='Week5.pdf') == 'other'
        assert classify_resource_type(restored, filename='Lecture examples.pdf') == 'lecture'
    assert classify_resource_type(weak, filename='Assignment1.pdf') == 'other'


def test_same_strength_direct_conflict_stays_other():
    lecture = resource_role_evidence(link_text='Lecture')
    tutorial = resource_role_evidence(item_title='Tutorial')
    reading = resource_role_evidence(nearby_text='Recommended readings')
    assert classify_resource_type(lecture + tutorial + reading) == 'other'
