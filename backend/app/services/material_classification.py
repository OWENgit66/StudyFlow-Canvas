"""Deterministic title/context policy; never infer a material's role from its extension."""
from dataclasses import dataclass
from enum import StrEnum
import re
import unicodedata
from app.models.common import ResourceType


def resource_role_evidence(**context):
    """Keep only role signals, not private text, while merging duplicate discoveries.

    Filenames, link/item labels and Page titles are direct signals (in that
    order). Module titles and nearby prose are weaker context. Explicit other
    intent competes only with weak context, including after duplicate merging.
    Conflicting signals at the strongest level mean 'other'.
    """
    priorities = {'filename': 4, 'display_name': 4, 'item_title': 3, 'link_text': 3,
                  'page_title': 2, 'module_title': 1, 'nearby_text': 0}
    signals = []
    for source, value in context.items():
        if source not in priorities or not isinstance(value, str):
            continue
        text = normalize(value)
        # Rank 1 blocks context-only inference, but never overrides direct
        # Lecture/Tutorial titles. Accept Assignment1, not "reassignment".
        if re.search(r'\b(?:assignments?|assessments?|homework|readings?)(?:\d+)?\b', text):
            signals.append((1, ResourceType.other.value))
        for role, pattern in ((ResourceType.lecture, r'\b(?:lectures?|lec)\b'),
                              (ResourceType.tutorial, r'\b(?:tutorials?|tut)\b')):
            if re.search(pattern, text):
                signals.append((priorities[source], role.value))
    return sorted(set(signals))


def classify_resource_type(evidence=(), **context):
    signals = [*evidence, *resource_role_evidence(**context)]
    if not signals:
        return ResourceType.other
    strongest = max(rank for rank, _ in signals)
    roles = {role for rank, role in signals if rank == strongest}
    return ResourceType(next(iter(roles))) if len(roles) == 1 else ResourceType.other


class MaterialKind(StrEnum):
    UNKNOWN = 'UNKNOWN'
    CORE = 'CORE_MATERIAL'
    READING = 'READING_MATERIAL'


@dataclass(frozen=True)
class Classification:
    kind: MaterialKind = MaterialKind.UNKNOWN
    # Only field names and matched policy phrases, never Page prose or URLs.
    reasons: tuple[str, ...] = ()


def normalize(value):
    return ' '.join(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', value).casefold()))


def combine(*decisions):
    """Reading evidence wins, independent of duplicate discovery order."""
    priority = {MaterialKind.UNKNOWN: 0, MaterialKind.CORE: 1, MaterialKind.READING: 2}
    kind = max((d.kind for d in decisions), key=priority.get, default=MaterialKind.UNKNOWN)
    reasons = tuple(dict.fromkeys(r for d in decisions if d.kind == kind for r in d.reasons))[:12]
    return Classification(kind, reasons)


class MaterialClassifier:
    def __init__(self, settings):
        self.rules = []
        for kind, terms in ((MaterialKind.READING, settings.material_reading_terms),
                            (MaterialKind.CORE, settings.material_core_terms)):
            for value in terms.split('|'):
                phrase = normalize(value)
                if phrase:
                    # Whole phrases, accepting common plural labels but not substrings like "collaboration".
                    suffix = '' if phrase.endswith('s') else 's?'
                    self.rules.append((kind, phrase, re.compile(r'\b' + re.escape(phrase) + suffix + r'\b')))

    def classify(self, **context):
        decisions = []
        for source, value in context.items():
            if not isinstance(value, str):
                continue
            text = normalize(value)
            for kind, phrase, pattern in self.rules:
                if pattern.search(text):
                    decisions.append(Classification(kind, (f'{source}:{phrase}',)))
        # "Chapter 6" alone is ambiguous: a lecture can also have chapter labels.
        # Reading Page/Module/link context still supplies explicit reading evidence.
        return combine(*decisions)
