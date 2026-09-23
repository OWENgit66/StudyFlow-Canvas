# StudyFlow V1 MVP completion

Release verification: 2026-09-23. **V1: Complete. V2: Not started.**

V1 delivers the local single-user Canvas → PDF → structured knowledge → database → learning interface workflow described in [README](../README.md). This completion task adds no features and makes no real Canvas or LLM requests.

## Final checks

| Check | Result |
| --- | --- |
| Full backend / API / provider / parser / sync tests | 458 passed, 1 skipped, 0 failed |
| Python dependency consistency (`pip check`) | No broken requirements |
| Frontend tests | 20 passed, 0 failed |
| TypeScript | Passed |
| ESLint | Passed |
| Next.js production build | Passed |
| Running FastAPI `/health` | HTTP 200 |

The backend skip is the existing Windows symlink-creation privilege test. Normal automated tests use isolated databases and synthetic fixtures, without real credentials or course downloads.

## Prior real-data acceptance

One authorized 41-page / 41-chunk lecture generation produced 35 accepted concepts, 35 key points, 5 questions and 4 examples, with no formulas or exam-focus entries. The current result was persisted with `stale=false`; the previous result was preserved in a local database snapshot and verified stale.

The real Dashboard → Course → Week workflow, persisted question show/hide, three source references and PDF page selection passed. Desktop and 390px mobile layouts were reviewed without horizontal overflow. A subsequent lecture-only UI sync reported one unchanged file and zero downloads, parses or AI analyses.

That prior generation used 9 DeepSeek requests, 32,446 input tokens, 13,427 output tokens and 45,873 total tokens. It is not repeated during this release task. Detailed course text, identifiers, screenshots and response captures remain in local evidence files where applicable, not in this summary.

## Source release hygiene

The workspace initially had no Git repository. A local repository was initialized for the requested MVP commit. No remote publication is part of this task.

- Environment files, private keys, databases/backups, downloads, caches, dependency directories, builds and temporary outputs are ignored.
- Only safe `.env.example` templates are included; credential placeholders are blank. The frontend ignore exception was corrected so its template is included.
- Private real-data screenshots, the live course-list report and detailed acceptance report remain local and ignored.
- Two course-derived regression fixture texts were replaced with synthetic unreadable-operator and incomplete-equation examples; the original fixture remains in ignored local data. The same safety assertions still run. Production behavior was not modified.
- The optional reusable synthetic preview helper and automated tests are source code; their generated PDFs, temporary databases and output files are not committed.
- Candidate/index files are checked for configured secret values and common credential patterns without printing secret values, as well as private/generated paths. Blank templates are checked separately.

## Known V1 limits

V1 is a trusted-local, single-user application, with synchronous sync requests and no authentication or public deployment support. OCR, non-PDF parsing, RAG and vector search are not implemented. Formula extraction and semantic review remain conservative heuristics; the user should check source pages when necessary. Some generated prose can be repetitive or contain an omission marker. These limits do not imply new feature work has started.

Historical phase reports describe their original point in development; use this release record and [roadmap](roadmap.md) for current status.
