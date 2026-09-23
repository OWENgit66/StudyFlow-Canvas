# Phase 6 — End-to-End Sync Workflow

> Historical Phase 6 implementation/verification record. Current semester selection,
> background polling, cancellation and startup recovery supersede the original
> behavior below; see [Active semester sync](active-semester-sync.md).

**Complete for the synchronous single-user MVP.** Phase 7 has not started. SyncService orchestrates existing services; it does not make Canvas HTTP calls directly, invoke PyMuPDF, call model APIs or duplicate validation. No new dependencies, workers, OCR, RAG or review stages were added.

## Workflow and identity

Select a local Semester → CanvasService.get_courses → upsert Course by canvas_course_id → get_modules → map Canvas module ID to Week → get_module_items → deduplicate File IDs → get_file canonical metadata → classify → download_resource → process_resource → KnowledgeService.generate → existing AI/provenance/formula/symbolic/semantic safeguards → atomic knowledge persistence → finalize SyncRecord.

Semester selection uses request.semester_id, then SYNC_SEMESTER_ID, then a scoped course's semester, or the only local Semester. Missing/ambiguous selection returns 422 before a run. No hard-coded year/term. Existing courses assigned to another semester are not moved. New courses discovered by an unscoped sync are assigned to the selected semester; Canvas academic-term membership is not inferred. Use course scope when appropriate.

Week retains the actual module title. Canvas module ID is the stable identity across renaming/reordering. An unambiguous legacy Week can be adopted by exact title or parsed Week/Module/Topic number; otherwise a free positive local week number is allocated. Unnumbered modules are valid. Multiple references to one Canvas file use the first canonical Resource association; existing ambiguous duplicate Resource IDs are reported, not overwritten.

## Incremental behavior

| Classification | Behavior |
|---|---|
| NEW | Create Resource, download into the existing human-readable materials structure, parse/chunk, generate and persist knowledge. |
| UPDATED | Same resource ID; newer Canvas timestamp. Invalidate current projections, replace the owned file, update metadata, replace chunks, regenerate knowledge. Historical canonical JSON remains if processing fails. |
| UNCHANGED, completed | Skip download, parser, chunk replacement and AI initialization/calls. Count files_skipped. Stale historical knowledge is not automatically regenerated. |
| UNCHANGED, incomplete/failed | Resume recorded download/parse/knowledge stage. Previously completed stages are retained. |
| Unsupported format | Download allowed; keep downloaded status with sync_stage=unsupported. Never call PDF parser or AI; later unchanged runs skip it. |

Missing/non-aware canonical update timestamps produce an isolated discovery error instead of claiming unchanged. Older or equal known timestamps are not treated as newer revisions. Existing owned paths are reused, including when upstream metadata is renamed; separate Canvas files with identical names use existing collision handling. Missing existing local files require explicit recovery rather than silently creating another duplicate.

Resource statuses remain the existing pending/downloaded/parsed/completed/failed values. sync_stage stores the next operation separately. Download commits before parsing; valid chunks commit before knowledge. A knowledge failure preserves both. On retry, process_resource is not repeated and chunks are not recreated; the existing KnowledgeService still validates the PDF's fresh warnings/chunk consistency before sending AI input. This intentional safety read is not counted as a new parse-and-persist stage.

## Lifecycle, errors and usage

Each run creates and commits a running SyncRecord before Canvas discovery. Progress is committed between stages. Final status is completed, completed_with_errors for isolated file/module/course failures, or failed for top-level discovery failure. completed_at is set at finalization. One file error does not prevent the next file from running.

Counters: files_discovered counts unique selected File IDs; files_downloaded counts all successful downloads including updates; files_updated is the successfully downloaded updated subset; files_skipped counts unchanged completed/unsupported files; files_failed counts failed discovered files. Discovery errors outside a file appear in details.errors and affect final status without inventing a file count. details adds files_parsed, files_analyzed, classification/stage events, safe stage/identity/error summaries and usage. Raw exception text, provider bodies, prompts, signed URLs and credentials are not logged.

Usage aggregates available AI request counts and only returned token counters, including bounded retries. requests_with_token_usage identifies partial token coverage. Absent counters are unknown, not invented zeros. An unchanged run never creates an AI provider; its usage map can be empty.

## APIs

`POST /api/sync` waits for completion and returns SyncRecordRead (identifier field `id`). The optional JSON body is:

```json
{
  "semester_id": 1,
  "course_id": 2,
  "module_id": 100,
  "file_id": 200
}
```

These IDs are illustrative placeholders; use IDs from your installation. course_id is a **local StudyFlow ID**; module_id/file_id are **Canvas IDs**. Module scope requires course scope; file scope requires module scope. Course scope is provided through this body instead of a redundant `/courses/{id}/sync` route.

`POST /api/sync?dry_run=true` performs discovery and classification, saving only the SyncRecord/progress. It does not create/update courses, weeks, resources or knowledge, download, parse or call AI.

`GET /api/sync/{sync_id}` returns persisted running/final progress; missing IDs return 404. Concurrent sync requests return 409 under the process-wide lock.

`GET /api/resources/{id}/knowledge` returns only current knowledge; absent/stale results return 404. `?include_stale=true` is the explicit audit/debug path and retains stale=true. Summary rebuilding excludes stale siblings. Updated resources lose outdated compatibility Concept/Question projections; original historical ResourceKnowledge payload is retained until a successful replacement.

## Schema and configuration

Three additive columns: Week.canvas_module_id (plus unique course/module index), Resource.sync_stage, SyncRecord.details JSON. `core/schema_upgrade.py` applies an idempotent SQLite upgrade during initialization. No table rebuild or manual SQL required. The development database was backed up before upgrading. `SYNC_SEMESTER_ID=` is optional in `.env.example`; no real secrets were changed.

## Verification

- Baseline Phase 1–5: **413 passed, 1 skipped**.
- Final full suite: **446 passed, 1 skipped, 0 failed**. The existing skip is Windows symlink privilege.
- Full mocked end-to-end workflow passed: fake Canvas discovery/download → real storage publication → real PDF parser/chunks → mock provider through real AI safety/semantic service → real SQLite knowledge persistence.
- Tests cover new/updated/unchanged, repeated sync, unchanged zero expensive calls, download/parse/AI failures and resume, isolated bad files/modules, identity/mapping, unsupported types, current vs historical reads, stale siblings in summaries, dry-run, scopes, usage, status APIs, progress visibility and additive upgrade preservation.
- Backend started normally; **GET /health = 200**, `{"status":"ok"}`.
- **GET /api/sync/1 = 200**, completed, files_skipped=1.
- Historical Resource 3: default knowledge GET **404**; explicit include_stale GET **200, stale=true**.

## Real-workflow verification summary

A single authorized unchanged-resource sync completed without download, parsing or AI calls. Original files, stored chunks and knowledge remained unchanged. Detailed Canvas identifiers and private evidence remain local. See [V1 verification](v1-release.md) for public aggregate results.

## Files created/modified

Added: `backend/app/services/sync_service.py`, `backend/app/repositories/sync.py`, `backend/app/api/sync.py`, `backend/app/schemas/sync.py`, `backend/app/core/schema_upgrade.py`, `backend/tests/test_sync.py`, this document.

Modified: `backend/app/models/week.py`, `resource.py`, `sync_record.py`; `backend/app/schemas/sync_record.py`; `backend/app/core/config.py`, `database.py`; `backend/app/main.py`; `backend/app/services/knowledge_service.py`; `backend/app/repositories/knowledge.py`; `backend/app/api/knowledge.py`; `backend/tests/test_knowledge.py`; `.env.example`, `README.md`, `docs/database.md`, `docs/ai-knowledge.md`.

## MVP limits

Run **one backend worker**. The lock is process-local; there are no distributed jobs, cancellation, automatic crash recovery or scheduler. A terminated process may leave a historical running record that needs inspection. File publication and SQLite commits are separate durability boundaries; catastrophic storage/DB failure may require local recovery. No remote Canvas deletions are propagated. Module/file multi-link associations are not modeled as many-to-many. Only PDFs are analyzed. Historical stale results are preserved and hidden by default; they require an explicit regeneration request to spend AI tokens. No Phase 7 UI was implemented.
