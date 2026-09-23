# Active semester sync and progress

V1 maintenance update. V2 remains not started. No paid AI calls are needed for configuration or dry-run checks.

## Scope

`Semester.is_active` is the single source of truth; a partial unique SQLite index permits at most one active row. `canvas_term_id` is an explicit unique mapping to Canvas's enrollment term. Configure an existing semester with `python -m app.configure_semester --semester-id <id> --canvas-term-id <id>` from backend while no sync is running. This does not move courses or start processing.

CanvasService fetches paginated courses with `include[]=term`. The dedicated `semester_scope.exclusion_reason` helper compares `enrollment_term_id` (or the returned term object's ID), rejects conflicting/missing IDs and inactive/restricted courses, and runs **before** any module/item/file discovery. It does not infer membership from course names. Course/date naming is not needed when stable Canvas term metadata exists. Canvas documents these fields in the [Courses API](https://developerdocs.instructure.com/services/canvas/resources/courses).

Request scopes can narrow the active semester but cannot expand it. Legacy `SYNC_SEMESTER_ID` should be blank; a conflicting value fails closed. A new install with no mapped active semester requires explicit setup. Historical courses, weeks, files, chunks and knowledge remain stored. GET courses defaults to active; an explicit `semester_id` can read history. Direct ID-based historical reads remain available.

## Runtime and API

- `POST /api/sync?background=true` reserves the single worker, persists a running record and returns HTTP 202 with its ID. An in-process FastAPI BackgroundTask owns its own database session. The synchronous API remains available for existing clients.
- `GET /api/sync/current` finds a running record; `GET /api/sync/{id}` supplies current progress. The UI polls approximately once per second and refreshes page data after a terminal state.
- `POST /api/sync/{id}/cancel` sets a process-local cancellation event. The worker alone writes telemetry to avoid lost updates between polling/cancellation and progress commits.
- Checkpoints before discovery, each processing stage, each generation/review request and persistence prevent subsequent work after cancellation. An in-flight HTTP request may have to return or time out. Completed resources remain valid; unfinished stages can be resumed only by a new explicit sync.
- Startup marks orphaned running records `cancelled` while preserving counters, usage and errors. It never resumes paid work automatically. Run **one backend process/worker**; process-local locking and startup recovery are not multi-worker scheduling.

Details include current course/module/file IDs and names, stage, explicit per-file step states, parsed/analyzed counts, errors, cancellation intent and a backend `updated_at`. Stage callbacks observe the existing AI and persistence paths without replacing safeguards. No schema migration is needed for this telemetry: it lives in the existing SyncRecord details JSON.

Discovery now collects a bounded-by-Canvas-pagination in-process list of unique selected file IDs and their module context **before** processing starts. Until discovery finishes, the UI shows an indeterminate bar, not a percentage. Once the total is known, progress is `(completed + skipped + failed) / files_discovered`; the currently processing resource is excluded. If discovery had errors, the UI continues to label the scope incomplete rather than claiming a full total. Dry runs count metadata checks separately and do not imply knowledge completion.

The current-file stepper reads explicit backend states for discovery, download, parse, generation, review and persistence. Successful returns/commits mark steps complete; a next-stage label alone does not imply prior success. Resume telemetry recognizes already-committed downloads/chunks. Generation batch numbers come from the existing bounded batch loop. AI retries retain the current batch and step. Failed files retain safe stage and identity details while the next file gets a fresh pipeline.

Elapsed time and the age of the last real backend update are displayed independently of polling. A slow request does not fake a heartbeat or an ETA. After a minute without new progress the UI explains that the current request may still be running. Finished/cancelled records show duration; cancellation reports completed, skipped, failed and not-processed discovered resources. Errors expand under Needs attention during and after processing, without raw exception bodies. Poll/start/cancel requests have a 15-second client timeout; repeated polling failures show uncertainty and stop the indefinite spinner without automatically starting another sync. Polls run sequentially and stop on all terminal statuses.

The Dashboard highlights the active semester. Cards show modules, parsed materials and **current** learning-note counts. Dry-run results are explicitly labelled as discovery-only, not completed knowledge processing. Courses not yet imported will appear only after an authorized full sync; a dry run never creates course records.

## Schema and existing data

The idempotent SQLite upgrade adds `Semester.is_active` and `canvas_term_id` plus unique indexes. It transactionally rebuilds the leaf SyncRecord table when needed to add the `cancelled` CHECK-constraint value, preserving all existing rows. No new queue or framework is introduced.

For this installation, the backend was already stopped when inspected. A SQLite backup was taken first. Orphaned Sync #4 was marked cancelled with a manual-stop explanation; its original counters, usage and errors remain. Existing imported courses were reassigned to their verified Canvas terms in SQLite. No materials, chunks or knowledge were deleted or moved. Some previously downloaded historical files still have the former incorrect active-semester folder prefix; registered paths remain unchanged and accessible.

Private inventory, backup and dry-run evidence are under ignored `data/semester-scope/`. The inventory covers all registered historical material paths; the only unregistered file in materials was `.gitkeep`. Archive/deletion requires a later user decision.

## Verification

Automated tests cover active/old/unknown/conflicting terms, exclusion before expensive work, dry-run counts, new/updated/unchanged behavior, safe cancellation across service boundaries, concurrent polling/cancel while a worker is blocked, duplicate-start rejection, schema upgrade preservation and explicit activation. Frontend tests cover active-only cards, telemetry, completion/failure/cancellation, safe error messages and polling failure recovery.

Final suites after the detailed progress update: **481 backend tests passed, 1 skipped** (existing Windows symlink privilege); **35 frontend tests passed**. TypeScript, ESLint and the Next.js production build passed. The local backend started normally, `/health` returned HTTP 200 and `/api/sync/current` returned null. No real external requests were made for the detailed progress update.

Browser verification used `python tests/preview_study.py --sync-progress`, an isolated synthetic snapshot with Canvas/LLM requests disabled. Desktop, 390px and 320px layouts were inspected; DOM width checks reported no horizontal overflow. Course → Week browsing and existing knowledge remained available with the progress panel visible. The preview was stopped after verification. Additional tests exercise discovery-to-known-total transitions, explicit step completion, batch display, failure states, cancellation remaining counts, non-overlapping requests and polling termination for all four final statuses.

The real Canvas dry run used the production API after automated checks passed: **16 courses visible, 4 included, 12 outside the active term; 109 files discovered (96 NEW, 13 UNCHANGED), 0 failures**. It downloaded nothing, parsed nothing and made no AI calls. SHA-256 snapshots of material files and all non-sync table contents were identical before/after; SQLite integrity was `ok` with no foreign-key violations. Only SyncRecord progress/result was written. A full paid sync remains pending explicit user confirmation.
