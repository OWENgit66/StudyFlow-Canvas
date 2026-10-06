# RAG V2 — Shared incremental course indexes

Course Q&A now uses the application's configured SQLite database, not an experiment snapshot. Historical V0/V1 indexes and Eval files remain unchanged.

## Storage and model identity

The existing `chunk_embeddings` table is reused. Its `chunk_id` FK joins DocumentChunk → Resource → Week → Course, so course/resource identifiers are not redundantly copied. The FK cascades normal chunk deletions. The table stores one current embedding per chunk with model, model_version, dimensions, content_hash, source_hash, generated_at and vector JSON. Historical models remain in the separate, preserved experiment snapshots; this is not a multi-version migration system.

The live runtime explicitly selects the existing `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions), using FastEmbed/ONNX on CPU with local-files-only loading. It reuses `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, cosine Top-5, retrieval hygiene and the existing bounded Answer Context. No model download, paid embedding endpoint or new vector database is introduced.

## Incremental work

`CourseIndexService.index_course()` wraps the existing `RetrievalService.index_course()`:

- New: no embedding row → generate.
- Changed/incompatible: content/source hashes, model/version/dimensions differ, or vector is corrupt → regenerate.
- Unchanged: all identity checks pass → skip, preserving generated_at.
- Stale: remove embeddings for now-unusable chunks in the selected course. Normal deleted chunks are already removed by FK cascade; legacy orphan embeddings are also cleaned.

The existing SHA-256 fingerprint covers text and source identity/page/chunk/provenance. Timestamps alone never determine compatibility. Role-only changes do not alter embedding input or force re-embedding; source labels and optional resource-type filtering use live Resource metadata.

Results: total_chunks (currently usable), new_embeddings, updated_embeddings, skipped_embeddings, removed_stale, unusable_chunks. removed_stale counts deletes performed by that run; earlier FK-cascade deletes are not counted again. Valid batches commit independently, so a later failed batch does not erase completed embeddings or any source chunks.

## Status and Q&A safety

One additive nullable JSON column, `courses.indexing_report`, records indexing/error and last-run statistics. ORM loading is deferred to keep old read-only snapshots readable. No source table is rebuilt.

`GET /api/courses/{id}/index-status` reports ready/indexing/stale/unavailable/error with a safe explanation. Ready requires every currently usable chunk to have a compatible, valid embedding. Partial indexes are stale. Empty courses are unavailable. Recorded failures are error until retried. Startup converts interrupted indexing flags to error; it never resumes paid work.

Course Q&A checks readiness before retrieval, before generation and before returning the answer. Every query uses the existing SQL course filter. Source IDs, text, page, role and course ownership are revalidated against live data; changed sources during generation fail closed. The generation prompt, citation rules, response shape and Answer Context selection remain unchanged. Runtime status does not require historical experiment files.

## Automatic sync integration

The production SyncService receives the local indexer through the existing sync factory. After material processing, each included course is indexed once. Dry runs do not index. The existing background sync worker handles the work; no queue or extra service is added. Sync stays visibly running during indexing, and Course Q&A polls its readiness every ten seconds.

Index errors are stored in the course report and `SyncRecord.details.indexing`. They do not turn successful material processing into file failures or roll it back. A subsequent sync retries indexing. Cancellation is observed between courses; the current local indexing operation finishes before the next cancellation checkpoint.

Single-user/single-backend-worker remains the supported deployment. An in-process lock serializes indexing, with an atomic database claim preventing two workers claiming the same course. Do not restart the backend during a maintenance CLI indexing run: startup recovery assumes existing indexing flags were interrupted.

## Maintenance CLI

From `backend`, using the existing retrieval dependencies and cached local models:

```powershell
.venv/Scripts/python.exe -m app.index_course --course-id 6 --status
.venv/Scripts/python.exe -m app.index_course --course-id 6
.venv/Scripts/python.exe -m app.index_course --all
```

Ordinary users only need Sync Canvas. These maintenance commands neither contact Canvas nor parse/download documents. A repeated index skips compatible rows. The existing Ask endpoint is the only step that invokes the configured LLM, once per submitted question with no hidden retry.

`--all` backfills existing courses from every semester sequentially through the same indexer. Courses without usable chunks are reported unavailable without loading the model. Ready courses skip compatible embeddings; a failed course is reported and does not stop later courses. Run it when no sync/indexing job is active. Per-course JSON progress is followed by a summary; any course error gives exit code 1. `--status` remains a single-course read-only option.

Summary `ready` is the final ready count; `ready_before` counts courses ready at their initial check. `newly_indexed` means all usable chunks were new embeddings; `stale_updated` counts other courses that generated any new/updated embeddings. New/updated/skipped embedding totals cover successful course runs; a failed run may still retain previously committed batches and is not included in those totals.

Private databases, vectors, caches, model weights, answers and validation reports remain under ignored storage. Do not publish course-derived artifacts.

Known answer-quality limits (including strict sentence-level grounding and formula reconstruction) are unchanged; indexing readiness is not a claim that every generated answer is correct.
