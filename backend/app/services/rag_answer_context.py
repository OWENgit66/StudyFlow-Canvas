"""Answer-only context balance; never changes retrieved ranks or stored chunks."""
from dataclasses import replace
import re

from sqlalchemy import select

from app.models import DocumentChunk, Resource, Week
from app.services.retrieval_service import usable
from app.services.retrieval_hygiene import low_information_reason


def exercise_prompt(hit):
    # A worked solution is useful explanatory evidence, not an unanswered exercise.
    if re.search(r'(?im)^\s*(?:worked\s+)?(?:solution|answer)\b', hit.text):
        return False
    return bool(re.search(r'(?i)^\s*(?:question|exercise|problem)\s*\d', hit.text)
                or (re.search(r'(?i)assignment|homework|exercise', hit.resource_title)
                    and re.search(r'(?i)\b(?:calculate|determine|give an example|what is)\b', hit.text)))


def section_terms(text, question):
    """Require a query term in the section heading, not a generic course header."""
    words = lambda value: set(re.findall(r'[a-z][a-z0-9]{1,}', value.lower()))
    stop = {'what', 'how', 'is', 'are', 'the', 'and', 'of', 'to', 'in', 'does', 'do', 'for', 'can', 'it'}
    heading = next((line.strip() for line in text.splitlines() if line.strip()), '')
    return (words(heading) & words(question)) - stop


def has_body(text):
    return len(re.findall(r'\b[A-Za-z]+\b', text)) >= 25


def select_answer_context(db, ranked, question, limit):
    selected = _select_balanced_context(db, ranked, question, limit)
    if db is None or len(selected) >= 5:
        return selected
    # Only bridge original selected anchors; additions never seed further expansion.
    ranked_ids = {h.chunk_id for h in ranked}
    anchors = [h for h in selected if h.chunk_id in ranked_ids]
    seen = {h.chunk_id for h in selected}
    added_pages = set()
    for left in anchors:
        heading = section_heading(left.text)
        if not heading or not section_terms(left.text, question):
            continue
        for right in anchors:
            if (left.resource_id != right.resource_id or left.course_id != right.course_id
                    or not left.page_number or not right.page_number
                    or not 2 <= right.page_number - left.page_number <= 3
                    or heading != section_heading(right.text)):
                continue
            resource = validated_resource(db, left)
            if resource is None or validated_resource(db, right) is None:
                continue
            chunks = db.scalars(select(DocumentChunk).where(
                DocumentChunk.resource_id == resource.id,
                DocumentChunk.page_number > left.page_number,
                DocumentChunk.page_number < right.page_number,
            ).order_by(DocumentChunk.page_number, DocumentChunk.chunk_index))
            for chunk in chunks:
                page = (resource.id, chunk.page_number)
                if (chunk.id in seen or page in added_pages or not usable(chunk, resource)
                        or heading != section_heading(chunk.content) or not has_body(chunk.content)
                        or low_information_reason(chunk.content)):
                    continue
                neighbor = neighbor_hit(left, resource, chunk)
                if exercise_prompt(neighbor):
                    continue
                selected.append(neighbor)
                seen.add(chunk.id)
                added_pages.add(page)
                if len(added_pages) == 2 or len(selected) == 5:
                    return selected
    return selected


def section_heading(text):
    heading = next((line.strip() for line in text.splitlines() if line.strip()), '')
    return ' '.join(heading.casefold().split()) if len(heading) <= 120 else ''


def validated_resource(db, anchor):
    resource = db.get(Resource, anchor.resource_id)
    week = db.get(Week, resource.week_id) if resource else None
    original = db.get(DocumentChunk, anchor.chunk_id)
    if (not week or week.course_id != anchor.course_id or week.id != anchor.week_id
            or resource.resource_type.value != anchor.resource_type
            or not original or original.resource_id != resource.id
            or original.content != anchor.text or original.page_number != anchor.page_number
            or not usable(original, resource)):
        return None
    return resource


def neighbor_hit(anchor, resource, chunk):
    report = (resource.parsing_report or {}).get('health', {})
    warnings = sorted({issue['category'] for issue in report.get('issues', [])
                       if issue.get('page_number') == chunk.page_number and 'category' in issue})
    # Source expansion is not a scored retrieval result.
    return replace(getattr(anchor, 'original', anchor), chunk_id=chunk.id, score=0.,
        text=chunk.content, page_number=chunk.page_number, resource_title=resource.filename,
        source_link=f'/api/resources/{resource.id}/file#page={chunk.page_number}' if resource.local_path else None,
        parsing_warnings=warnings, parsing_health=report.get('status', 'unknown'))


def _select_balanced_context(db, ranked, question, limit):
    prompts = [h for h in ranked if exercise_prompt(h)]
    explanatory = [h for h in ranked if not exercise_prompt(h) and has_body(h.text)
                   and (h.resource_type == 'lecture' or section_terms(h.text, question))]
    if not prompts or not explanatory:
        return ranked[:limit]
    # Retain reranked order within each role. At most one unanswered exercise;
    # short heading-only hits remain anchors, but do not crowd out body evidence.
    selected = (explanatory + prompts[:1])[:limit]
    seen = {h.chunk_id for h in selected}
    additions = 0
    anchors = explanatory + [h for h in ranked if not exercise_prompt(h) and h not in explanatory]
    for anchor in anchors:
        terms = section_terms(anchor.text, question)
        if not terms or not anchor.page_number:
            continue
        resource = validated_resource(db, anchor)
        if resource is None:
            continue
        adjacent = db.scalars(select(DocumentChunk).where(
            DocumentChunk.resource_id == resource.id,
            DocumentChunk.page_number.in_([anchor.page_number-1, anchor.page_number+1]),
        ).order_by(DocumentChunk.page_number, DocumentChunk.chunk_index))
        for chunk in adjacent:
            if (chunk.id in seen or not usable(chunk, resource) or not has_body(chunk.content)
                    or not terms & section_terms(chunk.content, question)):
                continue
            neighbor = neighbor_hit(anchor, resource, chunk)
            if exercise_prompt(neighbor):
                continue
            selected.append(neighbor)
            seen.add(chunk.id)
            additions += 1
            if additions == 2 or len(selected) == 5:
                return selected
    return selected
