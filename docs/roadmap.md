# StudyFlow roadmap

| Version | Status | Scope |
| --- | --- | --- |
| V1 MVP | **Complete** | Local single-user Canvas → PDF → structured AI knowledge → SQLite → learning UI |
| V2 | **Not started** | Scope and priorities require a separate decision; no implementation started |

## V1 delivered

- Next.js / TypeScript / Tailwind frontend and FastAPI / SQLAlchemy / SQLite backend.
- Semester, Course, Week, Resource, DocumentChunk, ResourceKnowledge, Summary, Concept, Question and SyncRecord models.
- Read-only Canvas integration, pagination, safe storage and incremental manual sync with unchanged-file skipping and per-file errors.
- PDF parsing and page-bound chunks, extraction metadata, conservative cleaning and quality warnings.
- OpenAI/DeepSeek provider abstraction, bounded retries, schema/source validation, formula/symbolic safeguards, semantic review and transactional persistence.
- Dashboard, Course and Week pages; persisted answer toggles, source-page links, original files, scoped sync and sync summaries.
- Backend/API and frontend regression suites, production build and completed real-data acceptance. See [V1 release verification](v1-release.md).

## V2 candidates — not started

Potential directions include search/RAG with explicit sources, additional document formats, and study tools such as bookmarks or revision aids. These are options, not commitments. Provider costs, source reliability and existing privacy boundaries must be reviewed before selecting work.

No V2 code, dependencies, infrastructure or new feature work is part of the V1 completion commit.
