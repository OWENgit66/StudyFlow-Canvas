"""Persist compact page warnings, bound to exact source bytes; reads never parse."""
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from app.schemas.parsing_health import ParsingHealth, ParsingIssue
from app.services.material_paths import resolve_database_path
from app.services.symbolic_safety import has_unreadable, unreadable, MALFORMED

LABELS = {
    'suspicious_formula_layout': ('Formula layout may be unreliable', 'Raised or lowered text may have lost its position. Compare formulas with the original slide.', 'warning'),
    'unusual_symbol_position': ('Symbol positioning needs review', 'A symbol has unusual positioning that plain text may not preserve.', 'warning'),
    'unreadable_symbol': ('Unreadable symbol detected', 'A PDF glyph could not be reliably interpreted. Check the original symbol.', 'warning'),
    'encoding_warning': ('Text encoding needs review', 'Replacement characters indicate that some source characters may be missing.', 'warning'),
    'empty_text': ('No extractable text', 'This page may be blank or image-only. Its contents were not interpreted as text.', 'critical'),
    'possible_scanned_page': ('Little or no extractable text', 'This may be a scanned or image-only page. Automatic text recognition is not available.', 'critical'),
    'suspicious_symbolic_expression': ('Suspicious mathematical expression', 'The extracted expression has an unreliable symbol pattern. No formula repair was attempted.', 'warning'),
    'layout_review_recommended': ('Text layout needs review', 'Text order or interleaving may not reflect the original slide layout.', 'warning'),
    'repeated_header_footer': ('Repeated page furniture cleaned', 'Repeated headers or footers were removed conservatively from learning text.', 'info'),
}


def source_fingerprint(resource, root: Path):
    if not resource.local_path:
        return None
    try:
        path = resolve_database_path(resource.local_path)
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            return None
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        identity = [resource.id, str(path), resource.file_type, str(resource.canvas_updated_at), digest]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    except (OSError, ValueError, RuntimeError):
        return None


def issue(page, code, count=1):
    label, explanation, severity = LABELS.get(code, ('Page needs review', 'Compare extracted text with the original PDF page.', 'warning'))
    return ParsingIssue(page_number=page, category=code, label=label, explanation=explanation,
                        severity=severity, occurrences=count)


def build_report(document):
    issues = []
    for page in document.pages:
        codes = {warning.code: warning.occurrences for warning in page.warnings}
        # Reuse Phase 5's source-fidelity detectors; never infer or repair symbols.
        if has_unreadable(page.raw_text):
            codes['unreadable_symbol'] = max(1, sum(unreadable(c) for c in page.raw_text))
        if MALFORMED.search(page.text):
            codes['suspicious_symbolic_expression'] = 1
        issues.extend(issue(page.page_number, code, count) for code, count in codes.items())
    review_pages = {i.page_number for i in issues if i.severity != 'info'}
    return ParsingHealth(status='review' if review_pages or document.possible_scanned_pdf else 'healthy',
        total_pages=document.total_pages, pages_with_text=document.pages_with_text,
        pages_need_review=len(review_pages), pages_with_encoding_warnings=document.pages_with_encoding_warnings,
        possible_scanned_pdf=document.possible_scanned_pdf, issues=issues)


def store_report(resource, fingerprint, report):
    resource.parsing_report = {'version': 1, 'resource_id': resource.id, 'fingerprint': fingerprint,
                               'health': report.model_dump(mode='json')}


def read_health(resource, root: Path):
    if resource.file_type.lower() not in {'pdf', '.pdf', 'application/pdf'}:
        return ParsingHealth(status='unsupported')
    fingerprint = source_fingerprint(resource, root)
    if fingerprint is None:
        return ParsingHealth(status='unavailable')
    stored = resource.parsing_report
    if not stored:
        return ParsingHealth(status='unknown')
    if stored.get('version') != 1 or stored.get('resource_id') != resource.id or stored.get('fingerprint') != fingerprint:
        return ParsingHealth(status='stale')
    try:
        report = ParsingHealth.model_validate(stored['health'])
        # Do not return private extraction messages accidentally added to stored JSON.
        report.issues = [issue(i.page_number, i.category, i.occurrences) for i in report.issues
                         if report.total_pages and i.page_number <= report.total_pages]
        return report
    except (ValidationError, KeyError, TypeError):
        return ParsingHealth(status='unknown')
