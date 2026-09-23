# Phase 7 — Student learning interface

Implemented on 2026-09-23 (Australia/Sydney). The Phase 1–6 processing services and database schema are unchanged. No real LLM request was made. No credentials or local `.env` files were modified.

## Pages and components

- `/`: semester selector (when needed), real course cards, module counts, parsed-material counts, latest module and latest sync summary. Counts describe preparation, not student completion. Empty semesters/courses have clear messages.
- `/courses/[id]`: course identity, ordered links using the actual Canvas module titles. Titles such as Revision or Assessment Resources are preserved.
- `/weeks/[id]`: overview → concepts → key points → reliable formulas → examples → conditional exam cues → practice questions → originals. When multiple resources have current knowledge, their items retain their own resource attribution.
- Shared header/breadcrumbs, `CourseCard`, `ConceptCard`, `QuestionCard`, `SourceReference`, `ResourceItem`, `SyncButton`, `SyncFeedback`, loading and retry components. A shared sync provider keeps navigation from starting duplicate requests within the app session.
- Warm paper background, deep green accents, serif headings, restrained borders and readable prose. Desktop has two-column course/concept cards and a small learning-section index. Narrow screens use a single column and wrap long titles/content. Keyboard focus, answer `aria-expanded`/`aria-controls`, status/error roles, and reduced-motion behavior are included.

## API and configuration

`frontend/src/lib/api.ts` centralizes fetch, API origin and safe errors. `types.ts` contains projections of actual API schemas. Reads use `cache: no-store`. Normal knowledge reads use the existing default-current-only resource endpoint. The client also rejects responses with `stale !== false` or the wrong resource ID; the rendering component checks again. Week content never reads historical Summary/Concept/Question projections directly. A knowledge read error leaves original materials accessible with a retry button.

Only these read-only backend additions were needed:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/study/dashboard` | All local semesters, course/module statistics, sanitized latest sync counters |
| `GET /api/weeks/{id}/resources` | Material filename/type/status/availability/size, without local paths |
| `GET /api/resources/{id}/file` | Registered original file; optional `download=true` |

`WeekRead` additionally exposes its existing nullable `canvas_module_id` for scoped sync. Generation, parsing, source validation and SyncService were not redesigned.

Frontend optional settings live in `frontend/.env.local`, using `frontend/.env.example`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=
BACKEND_API_URL=http://127.0.0.1:8000
```

Blank public origin uses the Next.js same-origin `/api` rewrite; this is the supported local setup and needs no CORS changes. `BACKEND_API_URL` is the Next server's upstream, not a browser secret. Restart/rebuild after changing these settings; public variables and rewrites are build-time configuration. A custom cross-origin public API would need its own CORS configuration; that deployment mode was not added here. Never copy Canvas or LLM keys into frontend environment variables. Backend `.env` behavior is unchanged.

## Source and file behavior

Sources display filename and page, linking to `/api/resources/{id}/file#page=N` in a new tab. The native PDF viewer handles page selection. If the original is unavailable, the citation remains text with its page number. There is no custom viewer or duplicate frontend file copy.

File access verifies the resource and resolves the registered path inside `MATERIALS_ROOT`, including symlink resolution. Outside paths, traversal, missing files and directories return a generic 404. PDF responses support range requests, use `application/pdf` and inline disposition; explicit downloads and other file types use attachment disposition. Responses include `nosniff` and `no-store`. No endpoint accepts a user-supplied filesystem path.

## Sync behavior

Dashboard sync posts the selected semester to existing `POST /api/sync`. Courses can sync individually. A module offers all its materials or one selected Canvas file, making a small scoped check possible. The button disables while pending, reports friendly failures, and shows an expandable result: courses, discovered files, new downloads, updated, skipped, failed. New downloads are `files_downloaded - files_updated` because the existing API includes updates in its download count.

The existing synchronous backend is retained. Next's proxy timeout is set to one hour to accommodate its bounded processing calls. No live per-file progress stream or job queue was introduced. If a network connection is lost, the UI warns that processing may still be running; it does not automatically repeat the POST. The backend's existing overlap lock remains authoritative. Reloading loses the client in-flight state, while Dashboard can still read the latest persisted record.

## Verification

Before changes: backend **446 passed, 1 skipped**; frontend lint/build passed (build required Windows child-process permission). The original frontend had no test runner.

After changes:

| Check | Result |
| --- | --- |
| Frontend Vitest + React Testing Library | **20 passed**, 0 failed |
| `npm run typecheck` | Passed |
| `npm run lint` | Passed |
| `npm run build` | Passed; all three routes built |
| Full backend pytest | **458 passed, 1 skipped**, 0 failed |
| FastAPI startup | Passed |
| `GET /health` | **200** |
| Browser error log on real UI | No JavaScript errors observed |

UI tests mock backend responses. They cover browsing, overview/concepts/all learning sections, source links, question toggles without network calls, original files, empty/missing/error states, retry, stale exclusions, unsafe formula omission, sync payloads/counters/disabled states/failure, and configuration separation. New backend tests cover real counts, safe presentation data, file containment, range/download responses and active-file attachment handling. The skipped test is the pre-existing host symlink privilege test; an additional containment test simulates symlink resolution without requiring that privilege.

### Public preview

With the production frontend running, execute `.venv/Scripts/python.exe tests/preview_study.py` from backend and open `http://127.0.0.1:3002`. This optional preview uses an isolated database, synthetic PDF and mocked AI, blocks POST requests and does not read real credentials. Detailed real-data walkthroughs remain local. See [V1 verification](v1-release.md) for aggregate results.

## Initial implementation status and follow-up

Real local screenshots are retained under ignored `docs/screenshots/` to keep private course information out of Git.

Changed files: frontend App Router pages/layout/CSS, `src/components/*`, `src/lib/*`, `next.config.ts`, `.env.example`, package manifests, Vitest configuration and `tests/*`; backend `api/study.py`, `schemas/study.py`, `schemas/week.py`, `main.py`, `tests/test_study.py` and the optional `tests/preview_study.py`; root/frontend README and this report. The existing processing services and secrets files were not edited.

At the initial implementation review, automated verification, real browsing, PDF/page opening and unchanged-file sync passed, but the full real-data Concepts/Questions walkthrough remained pending because existing knowledge was absent or stale. The fixture results above did not replace that acceptance check.

**Follow-up, 2026-09-23: Phase 7 is COMPLETE.** One explicitly authorized production DeepSeek generation supplied fresh current knowledge for the existing Week 2 lecture. The populated real application, question controls, source links, desktop/mobile layout and another unchanged lecture-only sync all passed. See [V1 verification](v1-release.md) for the public summary; detailed private source comparisons remain in the ignored local acceptance report.

No later phase was started.
