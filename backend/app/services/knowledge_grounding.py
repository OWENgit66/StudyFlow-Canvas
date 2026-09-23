"""Validate chunk provenance and attach evidence from application-owned sources."""
from dataclasses import dataclass, field
import re

from app.schemas.knowledge import GroundedKnowledgeOutput, KnowledgeInput, KnowledgeOutput
from app.services.ai_errors import AIResponseError, KnowledgeInputError
from app.services.symbolic_safety import FORMULA_RISKS, reliable_symbol_source, unsafe_symbolic_content
FIELDS = ('concepts', 'key_points', 'formulas', 'examples', 'exam_focus', 'questions')
EXAM_CUES = re.compile(r'\b(exams?|assessments?|quizzes|quiz|important|remember|learning outcomes?)\b'
                      r'|\b(?:midterm|final|practice|upcoming) test\b|\b(?:on|for) (?:the |a )?test\b'
                      r'|考试|考核|测验|学习目标|重点', re.IGNORECASE)
NEGATED_CUE = re.compile(r'\b(?:not|never|no|unimportant|excluded)\b|不考|非重点|无需记忆', re.IGNORECASE)


def has_exam_cue(text: str) -> bool:
    # Work on actual source lines, not LLM evidence. Generic technical "test"
    # (CRC tests, software tests, etc.) is deliberately insufficient.
    return any(EXAM_CUES.search(line) and not NEGATED_CUE.search(line) for line in text.splitlines())


def source_map(chunks: list[KnowledgeInput]) -> dict[int, KnowledgeInput]:
    if not chunks or len({c.resource_id for c in chunks}) != 1:
        raise KnowledgeInputError('Knowledge input must belong to exactly one resource.')
    result = {c.source_chunk_id: c for c in chunks}
    if len(result) != len(chunks):
        raise KnowledgeInputError('Stored source chunk IDs must be unique.')
    return result


@dataclass
class Filtering:
    formulas: int = 0
    exam_focus: int = 0
    optional: dict[str, int] = field(default_factory=dict)
    formula_filtered: dict[str, int] = field(default_factory=dict)
    formula_reduced: dict[str, int] = field(default_factory=dict)

    def formula_drop(self, category: str):
        self.formula_filtered[category] = self.formula_filtered.get(category, 0) + 1
        self.drop(category)

    def drop(self, category: str):
        if category in {'formulas', 'examples', 'exam_focus'}:
            self.optional[category] = self.optional.get(category, 0) + 1
        if category == 'formulas':
            self.formulas += 1
        if category == 'exam_focus':
            self.exam_focus += 1


def validate_grounding(output: KnowledgeOutput, chunks: list[KnowledgeInput], *,
                       source_chunks: list[KnowledgeInput] | None = None
                       ) -> tuple[GroundedKnowledgeOutput, Filtering]:
    # Full originals retain evidence when a long chunk is split for prompts.
    originals = source_map(source_chunks if source_chunks is not None else chunks)
    allowed = {c.source_chunk_id for c in chunks}
    for chunk in chunks:
        original = originals.get(chunk.source_chunk_id)
        if (original is None or chunk.resource_id != original.resource_id
                or chunk.page_number != original.page_number):
            raise KnowledgeInputError('Batch source identity differs from stored chunks.')
    filtered = Filtering()
    values = output.model_dump()
    # Uncited summaries never survive: semantic review derives these from safe,
    # supported items. Discard them now so they cannot cause a batch failure.
    values['topic'] = values['overview'] = ''
    for category in FIELDS:
        kept = []
        for item in getattr(output, category):
            try:
                ids = item.source_chunk_ids
                if len(set(ids)) != len(ids) or not set(ids) <= allowed:
                    raise AIResponseError('LLM invented, duplicated or cited an out-of-batch source chunk ID.')
                sources = [originals[i] for i in ids]
                pages = [item.source_page] if category == 'formulas' else item.source_pages
                if len(set(pages)) != len(pages) or set(pages) != {c.page_number for c in sources}:
                    raise AIResponseError('Source pages do not match the cited chunks.')
                if category == 'formulas':
                    if (not all(reliable_symbol_source(c) for c in sources)
                            or not item.reliable or not item.formula.strip()
                            or not any(item.formula in c.content for c in sources)):
                        filtered.formula_drop(category)
                        continue
                data = item.model_dump()
                unsafe = [k for k, v in data.items() if isinstance(v, str)
                          and k != 'importance' and unsafe_symbolic_content(v, sources)]
                if unsafe:
                    if category == 'concepts' and 'name' not in unsafe:
                        for key in unsafe:
                            data[key] = ''
                        if data['definition'].strip() or data['explanation'].strip():
                            filtered.formula_reduced[category] = filtered.formula_reduced.get(category, 0) + 1
                        else:
                            filtered.formula_drop(category)
                            continue
                    else:
                        filtered.formula_drop(category)
                        continue
                if category == 'exam_focus' and not any(has_exam_cue(c.content) for c in sources):
                    filtered.drop(category)
                    continue
                # Replace every model quote with the real stored chunk content.
                data['evidence'] = [{'source_chunk_id': c.source_chunk_id, 'page_number': c.page_number,
                                     'quote': c.content, 'warnings': c.warnings} for c in sources]
                data['source_warnings'] = sorted({w for c in sources for w in c.warnings})
                kept.append(data)
            except AIResponseError:
                if category not in {'exam_focus', 'examples'}:
                    raise  # Core citation failures remain atomic failures.
                filtered.drop(category)
        values[category] = kept
    return GroundedKnowledgeOutput.model_validate(values), filtered
