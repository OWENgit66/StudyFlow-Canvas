# StudyFlow roadmap

| Version | Status | Scope |
| --- | --- | --- |
| V1 MVP | **Complete** | Local single-user Canvas → PDF → structured AI knowledge → SQLite → learning UI |
| V2.1 | **Complete** | Resource roles: lecture / tutorial / other; additive migration, API metadata and Week-page labels |
| V2.2–V2.6 | **Not started** | Visual pages; separate knowledge pipelines; embeddings; course RAG; multimodal RAG, in that order |

## V1 delivered

- Next.js / TypeScript / Tailwind frontend and FastAPI / SQLAlchemy / SQLite backend.
- Semester, Course, Week, Resource, DocumentChunk, ResourceKnowledge, Summary, Concept, Question and SyncRecord models.
- Read-only Canvas integration, pagination, safe storage and incremental manual sync with unchanged-file skipping and per-file errors.
- PDF parsing and page-bound chunks, extraction metadata, conservative cleaning and quality warnings.
- OpenAI/DeepSeek provider abstraction, bounded retries, schema/source validation, formula/symbolic safeguards, semantic review and transactional persistence.
- Dashboard, Course and Week pages; persisted answer toggles, source-page links, original files, scoped sync and sync summaries.
- Backend/API and frontend regression suites, production build and completed real-data acceptance. See [V1 release verification](v1-release.md).

## V2 next steps — not started

V2.1 is limited to resource classification. V2.2 DocumentPage and visual preservation require a separate task. Knowledge prompts, embeddings and RAG remain unchanged and unimplemented for V2. See AGENTS.md for the ordered plan.

No V2 code, dependencies, infrastructure or new feature work is part of the V1 completion commit.
