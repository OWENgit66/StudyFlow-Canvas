"""Atomic resource replacement and compatibility projections into existing knowledge tables."""
from sqlalchemy import delete,select
from sqlalchemy.orm import Session
from app.models import ResourceKnowledge,Resource,Summary,Concept,Question
from app.schemas.knowledge import ExtractionResult


def save_knowledge(db:Session, resource:Resource, result:ExtractionResult, fingerprint:str, provider:str, model:str,
                   *, current_resource_ids: set[int]):
    row=db.get(ResourceKnowledge,resource.id)
    if row is None:
        row=ResourceKnowledge(resource_id=resource.id)
        db.add(row)
    row.payload=result.model_dump(mode='json')
    row.source_fingerprint=fingerprint
    row.provider=provider
    row.model=model
    for cls in (Concept,Question):
        db.execute(delete(cls).where(cls.resource_id==resource.id))
    for c in result.knowledge.concepts:
        db.add(Concept(resource_id=resource.id,week_id=resource.week_id,name=c.name,
                       definition=c.definition,explanation=c.explanation,importance=c.importance,
                       source_page=c.source_pages[0]))
    for q in result.knowledge.questions:
        db.add(Question(resource_id=resource.id,week_id=resource.week_id,question=q.question,
                        answer=q.answer,source_page=q.source_pages[0]))
    db.flush()
    rebuild_summary(db, resource.week_id, current_resource_ids)
    return row


def rebuild_summary(db, week_id, current_resource_ids):
    # Summary remains one per week. Rebuild from all resource results, not only the last resource.
    records=db.scalars(select(ResourceKnowledge).join(Resource,Resource.id==ResourceKnowledge.resource_id)
                       .where(Resource.week_id==week_id, Resource.id.in_(current_resource_ids))
                       .order_by(ResourceKnowledge.resource_id)).all()
    summary=db.scalar(select(Summary).where(Summary.week_id==week_id))
    if summary is None:
        summary=Summary(week_id=week_id,overview='')
        db.add(summary)
    overview,key_points,exam_focus=[],[],[]
    for record in records:
        knowledge=ExtractionResult.model_validate(record.payload).knowledge
        if knowledge.overview:
            overview.append(f'Resource {record.resource_id}: {knowledge.overview}')
        for field,destination in [('key_points',key_points),('exam_focus',exam_focus)]:
            for point in getattr(knowledge,field):
                pages=', '.join(map(str,point.source_pages))
                destination.append(f'{point.content} [Resource {record.resource_id}, pages {pages}]')
    summary.overview='\n\n'.join(overview)
    summary.key_points=key_points
    summary.exam_focus=exam_focus
    db.flush()
