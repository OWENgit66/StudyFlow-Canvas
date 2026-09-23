# Document parsing health and review

Each PDF in Original materials now shows its parsing review state: no detected review-level issues, pages needing review, possible scanned PDF, unable to parse, or an explicit unavailable/outdated report. Expanding Review issues groups friendly explanations by **1-based PDF page number**. Open page links use the existing registered-resource endpoint with `#page=N`; users are told which page to navigate to if their viewer ignores the fragment. No local paths, raw text, spans, bbox coordinates or exceptions are exposed.

The Dashboard contains course navigation and live sync progress, without document parsing-review counts or page-level warnings. Course views summarize materials needing review by module, separately from unavailable reports. Inside a Week, Original materials shows each Resource's health and review-page count. Exact page numbers, warning types and Open page links appear only after expanding Review issues. Warnings alone do not increment failed-file counts; actual unreadable/scanned/no-usable-text parse failures keep existing failure behavior.

## Storage and provenance

Phase 4 previously returned page warnings without persisting them on the Resource. A nullable `Resource.parsing_report` JSON column now stores a compact health report, version, Resource identity and source fingerprint. The additive SQLite startup upgrade preserves existing rows. `process_resource` saves the report alongside its existing chunk/status transaction. Failed parsing saves a safe failure state. No DocumentChunk fields or AI provider contracts changed.

The report reuses Phase 4 layout, encoding, empty/scanned page and margin-cleanup warnings, plus Phase 5's existing unreadable-symbol and malformed-expression detectors. It does not reconstruct formulas or add a scoring system. Repeated-margin cleanup is informational and does not count as a page requiring review. The count is distinct affected pages, not the number of warnings.

Before returning a report, the backend compares its Resource ID and fingerprint with the current source. The fingerprint includes exact PDF bytes, registered path, file type and Canvas update metadata. A changed source returns `stale` without old issues; missing/inaccessible files return `unavailable`; an existing file without a report returns `unknown`. Read endpoints hash source bytes but **never reparse, download, generate knowledge or mutate the database**. A clean report means no known warning was detected, not a guarantee of extraction accuracy.

API additions:

- `GET /api/weeks/{id}/resources`: `parsing_health` with status, total/text/review/encoding page counts, possible-scanned flag and safe issues.
- `GET /api/courses/{id}/weeks` and `GET /api/weeks/{id}`: resource count, materials needing review and unavailable parsing-report count.
- Existing sync details: `progress.parsing_review_pages`, independent of `files_failed`; retained as telemetry and not displayed in the live sync panel.

## Existing local PDFs

To populate reports for existing **active-semester** PDFs, stop/finish any sync and run from backend:

```powershell
.venv\Scripts\python.exe -m app.refresh_parsing_health
```

This explicit maintenance command only reads local active-semester PDFs and writes their report JSON (and normal Resource update timestamp). It does not replace chunks, modify knowledge or processing status, download materials, or call AI. Historical semesters are not parsed automatically. Back up the local database before maintenance; no startup backfill runs implicitly.

For this installation, a database backup and content-preservation snapshot were created under ignored `data/parsing-health-validation/`. Backfill results: **12 PDFs reviewed: 6 healthy, 6 needing review; 1 Resource had no available file**. All original material hashes, chunks, knowledge, sync history and preexisting Resource fields other than update timestamps were unchanged. SQLite integrity passed with zero foreign-key violations. Private warnings remain in the local database.

## Verification

- Backend: **489 passed, 1 skipped** (existing Windows symlink privilege).
- Frontend: **44 passed**.
- TypeScript, ESLint and production build passed; `/health` returned 200 and no sync was active.
- Tests cover healthy/unknown/stale/missing/failed reports, exact page numbers, safe response fields, warning categories, expansion/collapse, safe source links, overview counts, active-only backfill preservation and warnings not becoming sync failures.
- Synthetic browser QA: `python tests/preview_study.py --parsing-review`; real synthetic superscript and empty PDF pages, mocked AI, long filename. Desktop and 390px/320px layouts were inspected; no horizontal overflow. The preview was stopped afterward.
- No real Canvas sync or paid AI request was made for this update.
