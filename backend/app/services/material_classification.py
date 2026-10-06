"""Deterministic title/context policy; never infer a material's role from its extension."""
from dataclasses import dataclass
from enum import StrEnum
import re
import unicodedata
from app.models.common import ResourceType


def resource_role_evidence(**context):
    """Bounded role evidence; repeated words/duplicate discoveries add no votes."""
    priorities = {'filename': 12, 'display_name': 12, 'item_title': 10, 'link_text': 10,
                  'page_title': 8, 'module_title': 4, 'nearby_text': 2}
    signals = []
    for source, value in context.items():
        if source not in priorities or not isinstance(value, str):
            continue
        text = normalize(value)
        if re.search(r'\b(?:assignments?|assessments?|homework|readings?|syllabus|course outline|'
                     r'projects?|exams?|rubrics?|announcements?|reference materials?)(?:\d+)?\b', text):
            signals.append((max(5, priorities[source] - 1), ResourceType.other.value))
        for role, pattern in ((ResourceType.lecture, r'\b(?:lectures?|lec)\b'),
                              (ResourceType.tutorial, r'\b(?:tutorials?|tut)\b')):
            if re.search(pattern, text):
                signals.append((priorities[source], role.value))
        for role, pattern in (('lecture', r'\b(?:slides?|presentation|topic overview|concepts)\b'),
                              ('tutorial', r'\b(?:exercises?|worksheets?|practice|solutions?|answers?|labs?|practicals?|workshops?)\b')):
            if re.search(pattern, text):
                signals.append((3 if priorities[source] >= 8 else 1, role))
    return sorted(set(signals))


def classify_resource_type(evidence=(), **context):
    return score_resource_metadata(evidence, **context).resource_type


@dataclass(frozen=True)
class RoleDecision:
    resource_type: ResourceType = ResourceType.other
    confidence: float = 0.0
    method: str = 'metadata'
    reason: str = 'Insufficient role evidence.'


def score_resource_metadata(evidence=(), **context):
    signals = set(map(tuple, evidence)) | set(resource_role_evidence(**context))
    scores = {}
    for role in ResourceType:
        weights = sorted({weight for weight, name in signals if name == role.value}, reverse=True)
        # Strongest direct evidence dominates; corroboration contributes at most one point.
        scores[role] = weights[0] + (1 if len(weights) > 1 else 0) if weights else 0
    if any(weight >= 8 and role in {'lecture', 'tutorial'} for weight, role in signals):
        # Preserve V2.2a direct-title precedence (e.g. Reading.pdf linked as Tutorial
        # examples). Conflicting purpose still reduces the confidence/margin.
        scores[ResourceType.other] = min(scores[ResourceType.other], 6)
    ranking = sorted(scores, key=scores.get, reverse=True)
    winner = ranking[0]
    strength, margin = scores[winner], scores[winner] - scores[ranking[1]]
    supported = strength >= 4 or (2, winner.value) in signals
    if not supported or margin < 2:
        return RoleDecision(confidence=0.2 if strength else 0.0,
                            reason='Weak or conflicting role evidence.')
    confidence = 0.9 if strength >= 7 and margin >= 3 else 0.65
    return RoleDecision(winner, confidence, reason='Direct role evidence.' if confidence >= 0.8
                        else 'Low-strength or competing role evidence; review or fallback needed.')


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
