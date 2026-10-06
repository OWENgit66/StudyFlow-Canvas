"""Conservative text-only candidate exclusions, not document classification.

Unknown short text, formulas and diagram labels are retained. Neither page
number, resource ID, course vocabulary nor query/Gold labels are used.
"""
import re


# Evidence of prose/instructions/calculation makes these narrow templates unsafe.
_BODY = re.compile(
    r'[?!=<>。！？]|https?://|\b(?:is|are|was|were|means|defines?|contains?|'
    r'consists?|provides?|uses?|used|can|must|should|will|has|have|calculat\w*|'
    r'compute|computes|show|explain|consider|find|detect\w*|transmit\w*|receiv\w*|'
    r'connects?|supports?|governs?|carries|forwards?|identif\w*|responsible)\b', re.I)
_COURSE = re.compile(r'^[A-Z]{2,8}\s?\d{3,5}\s*:\s*\S')
_WEEK = re.compile(r'^(?:Week|Lecture|Session)\s+\d+\s*[:–-]\s*\S', re.I)
_AFFILIATION = re.compile(r'^(?:School|Department|Faculty) of\s+\S', re.I)
_ITEM = re.compile(r'^(?:\d+[.)]|[-–•❑▪])\s*(\S.*)$')


def low_information_reason(text: str) -> str | None:
    """Only exclude metadata covers and explicitly labeled topic-only outlines."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or _BODY.search(text):
        return None
    words = text.split()
    if (4 <= len(lines) <= 12 and len(words) <= 60
            and all(len(line.split()) <= 10 for line in lines)
            and _COURSE.match(lines[0])
            and any(_WEEK.match(line) for line in lines)
            and any(_AFFILIATION.match(line) for line in lines)
            and not any(_ITEM.match(line) for line in lines)):
        return 'title/cover-like content: short course + session + affiliation metadata'
    if lines[0].casefold() in {'syllabus', 'outline', 'table of contents'} and len(words) <= 200:
        # Multi-column extraction can place two numbered topics on one line.
        items = [part for line in lines[1:] for part in re.split(r'\s{3,}', line)]
        matches = [_ITEM.fullmatch(item) for item in items]
        if (len(items) >= 3 and all(matches)
                and all(len(match[1].split()) <= 10 for match in matches)):
            return 'outline-like content: explicit heading with only short listed topics'
    return None
