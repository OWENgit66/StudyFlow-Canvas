from unittest.mock import Mock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError

from app.core.database import build_engine
from app.core.schema_upgrade import upgrade_sync_columns
from app.models import Resource, DocumentChunk
from app.models.common import ResourceType
from app.schemas.resource import ResourceCreate, ResourceRead
from app.schemas.canvas import CanvasModuleItem, CanvasPage
from app.services.material_classification import classify_resource_type, resource_role_evidence
from test_sync import run, sync_setup


@pytest.mark.parametrize('context,expected', [
    ({'filename':'Week 4 Lecture Slides.pdf'}, 'lecture'),
    ({'filename':'Lecture 05 - Network Layer.pdf'}, 'lecture'),
    ({'filename':'Week 4 Tutorial.pdf'}, 'tutorial'),
    ({'filename':'Tutorial Solutions Week 6.pdf'}, 'tutorial'),
    ({'filename':'Exercises.pdf','page_title':'Week 5 Tutorial'}, 'tutorial'),
    ({'filename':'Notes.pdf','page_title':'Week 5 Lecture'}, 'lecture'),
    ({'filename':'Exercises.pdf','module_title':'Tutorial'}, 'tutorial'),
    ({'filename':'Slides.pdf'}, 'other'),
    ({'filename':'Workshop.pdf'}, 'other'),
    ({'filename':'abc.pdf'}, 'other'),
    ({'filename':'Lecture and Tutorial.pdf'}, 'other'),
    ({'filename':'Tutorial.pdf','page_title':'Lecture and Tutorial'}, 'tutorial'),
    ({'filename':'Week4_LEC.pdf'}, 'lecture'),
    ({'filename':'Week4_TUT.pdf'}, 'tutorial'),
    ({'filename':'Molecular.pdf'}, 'other'),
])
def test_role_rules(context, expected):
    assert classify_resource_type(**context) == expected


def test_duplicate_context_conflict_is_order_independent():
    a=resource_role_evidence(link_text='Lecture')
    b=resource_role_evidence(link_text='Tutorial')
    assert classify_resource_type(a+b) == classify_resource_type(b+a) == 'other'


def test_additive_migration_preserves_legacy_rows_and_is_repeatable():
    engine=build_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE resources (id INTEGER PRIMARY KEY, canvas_file_id INTEGER, local_path TEXT)'))
        conn.execute(text("INSERT INTO resources VALUES (1, 123, 'materials/example.pdf')"))
        conn.execute(text('CREATE TABLE document_chunks (id INTEGER PRIMARY KEY, resource_id INTEGER REFERENCES resources(id), content TEXT)'))
        conn.execute(text("INSERT INTO document_chunks VALUES (1, 1, 'Synthetic source')"))
    upgrade_sync_columns(engine)
    upgrade_sync_columns(engine)
    with engine.begin() as conn:
        assert conn.execute(text('SELECT id,canvas_file_id,local_path,resource_type FROM resources')).one() == (1,123,'materials/example.pdf','other')
        assert conn.execute(text('SELECT content FROM document_chunks')).scalar_one() == 'Synthetic source'
        conn.execute(text("UPDATE resources SET resource_type='tutorial' WHERE id=1"))
    upgrade_sync_columns(engine)
    with engine.begin() as conn:
        assert conn.execute(text('SELECT resource_type FROM resources')).scalar_one() == 'tutorial'
        assert conn.execute(text('PRAGMA foreign_key_check')).all() == []
        with pytest.raises(IntegrityError):conn.execute(text("UPDATE resources SET resource_type='lab'"))
    engine.dispose()


def test_schemas_and_week_resource_api(client, db, graph):
    resource=graph[-1]
    assert ResourceRead.model_validate(resource).resource_type == ResourceType.other
    with pytest.raises(ValidationError):
        ResourceCreate(week_id=1,filename='a.pdf',file_type='pdf',resource_type='lab')
    resource.resource_type=ResourceType.tutorial
    db.commit()
    response=client.get(f'/api/weeks/{resource.week_id}/resources')
    assert response.status_code==200 and response.json()[0]['resource_type']=='tutorial'
    assert 'local_path' not in response.json()[0]


@pytest.mark.parametrize('filename,expected', [('Lecture.pdf','lecture'),('Tutorial Solutions.pdf','tutorial'),('Other.pdf','other')])
def test_direct_file_role(db,sync_setup,filename,expected):
    sync_setup[1].metadata[201].filename=filename
    assert run(db,sync_setup).status=='completed'
    assert db.scalar(select(Resource)).resource_type==expected


@pytest.mark.parametrize('label,expected', [('Lecture','lecture'),('Tutorial','tutorial')])
def test_page_context_role(db,sync_setup,label,expected):
    canvas=sync_setup[1]
    sync_setup[0].settings.canvas_base_url='https://canvas.example.test'
    canvas.metadata[201].filename='Exercises.pdf'
    canvas.get_module_items=Mock(return_value=[CanvasModuleItem(id=1,module_id=51,title='Week 5',type='Page',page_url='week')])
    canvas.get_page=Mock(return_value=CanvasPage(page_id=1,url='week',title=f'Week 5 {label}',body='<a href="/files/201">Exercises</a>'))
    assert run(db,sync_setup).status=='completed'
    assert db.scalar(select(Resource)).resource_type==expected


def test_unchanged_file_can_gain_role_without_reprocessing_or_invalidating_knowledge(db,sync_setup):
    canvas=sync_setup[1]
    canvas.metadata[201].filename='Exercises.pdf'
    run(db,sync_setup)
    resource=db.scalar(select(Resource)); chunk=db.scalar(select(DocumentChunk))
    before=(resource.id,resource.canvas_updated_at,resource.updated_at,resource.local_path,chunk.id,chunk.content)
    calls=(len(canvas.downloads),sync_setup[2].parse.call_count,sync_setup[5].call_count)
    canvas.get_module_items=Mock(return_value=[CanvasModuleItem(id=1,module_id=51,title='Week 5 Tutorial',type='File',content_id=201)])
    dry=run(db,sync_setup,dry_run=True)
    db.refresh(resource)
    assert resource.resource_type=='other' and dry.files_downloaded==0
    result=run(db,sync_setup)
    db.refresh(resource);db.refresh(chunk)
    assert resource.resource_type=='tutorial' and result.files_skipped==1
    assert before==(resource.id,resource.canvas_updated_at,resource.updated_at,resource.local_path,chunk.id,chunk.content)
    assert calls==(len(canvas.downloads),sync_setup[2].parse.call_count,sync_setup[5].call_count)
    assert not sync_setup[3].read(db,resource.id).stale
