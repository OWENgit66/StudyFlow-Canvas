# Resource classification — V2.2

V1 remains the stable foundation. Resources now carry an educational `resource_type`: `lecture`, `tutorial`, or `other`. This is separate from the existing CORE/READING/UNKNOWN processing policy; readings are still intentionally ignored by default.

## Storage and migration

One non-null Resource column is added with a database and application default of `other`, constrained to the three supported values. The existing idempotent SQLite startup upgrade uses `ALTER TABLE ADD COLUMN`. It does not recreate tables or the database, change identifiers or paths, or delete chunks/knowledge. Repeated startup preserves assigned roles.

Existing V1 Resources initially become `other`. Migration does not guess roles from incomplete historical metadata or contact Canvas. New ordinary syncs classify discovered resources; an unchanged file can receive a role update without downloading, parsing or calling AI. The metadata-only update preserves `updated_at` and Canvas timestamps, so current knowledge remains current. Dry runs never persist role changes. Ignored readings remain untouched.

## Central rules

The existing `services/material_classification.py` owns metadata evidence scoring. Normalization handles case, Unicode, underscores and punctuation. It does not read files or call an LLM. The independent CORE/READING/UNKNOWN download policy is unchanged.

Explicit Lecture/Tutorial signal weights are:

1. Canonical filename / display name: 12.
2. Module Item title / link text: 10.
3. Page title: 8.
4. Module title: 4.
5. Nearby text: 2.

Other-purpose evidence (assignment, assessment, homework, reading, syllabus, course outline, project, exam, rubric, announcement, reference material) scores one below its source weight, with a floor of 5. It defeats broad Lecture context. To preserve the V2.2a direct-title contract, an explicit direct Lecture/Tutorial title caps Other's competing score at 6; conflict still reduces the confidence margin. Generic slides/presentation/concepts and exercises/solutions/lab/practical/workshop receive only weak evidence (3 direct, 1 contextual), not an unconditional category.

For each role, the strongest weight plus at most one corroborating point is used. Repeated words/duplicate discoveries cannot inflate scores. A winning margin below 2, unsupported weak evidence or no evidence yields low-confidence Other. Strength at least 7 and margin at least 3 give 0.9 confidence; otherwise a supported winner has 0.65. Module/nearby-only predictions remain compatible but can now invoke fallback. These are **heuristic confidence levels, not measured probabilities or accuracy**. No course identifiers or subject-topic mappings appear in the rules.

## Existing text and optional LLM fallback

`ResourceClassificationService` checks manual ownership first, then metadata. Only confidence below 0.8 reads existing DocumentChunks: at most three rows ordered by page/chunk, SQL-truncated and combined to at most 1,000 characters. Pending download/parse/unsupported stages do not use potentially old text. It never opens a PDF. Short explicit role headings can resolve the role; a generic Overview heading alone cannot. Conflicting headings remain uncertain.

Only metadata and content that remain uncertain may use the existing LLMProvider. The JSON schema requires exactly resource_type, numeric confidence in [0,1], and a short reason. The prompt classifies educational role, rejects topic-only guesses, and treats input as untrusted data. Each metadata field is bounded to 500 characters, opening text to 1,000, and merged evidence to 64 entries. Invalid/empty responses and provider errors fall back safely; no retries. Low-confidence valid LLM output becomes Other.

Normal Canvas sync uses metadata and existing text **without paid classification calls**. The standalone reclassification CLI can opt into at most 1–3 provider attempts for its entire run. Factory selection uses existing LLM_PROVIDER / LLM_MODEL / credentials. No new vendor configuration is introduced.

## Classification-only reprocessing

From `backend`, after normal backend startup has applied the additive migration:

```powershell
.venv/Scripts/python.exe -m app.reclassify --course-id 2 --limit 10
.venv/Scripts/python.exe -m app.reclassify --resource-id 123 --apply
# Explicit paid opt-in, only after inspecting an offline preview:
.venv/Scripts/python.exe -m app.reclassify --resource-id 123 --llm-max-calls 1 --apply
```

Default execution is preview, no database mutation and no LLM. Scope is mandatory. Apply updates classification only and skips manual records. It does not download, parse, regenerate knowledge/embeddings, resync Canvas or update RAG indexes. A repeated explicitly paid run can spend its budget again; no claim of provider-response caching is made. Historical missing metadata is not invented: available filename/Week and existing text are used. New syncs retain bounded discovery metadata and merged role signals for later reclassification.

## API and interface

`ResourceCreate`/`ResourceRead` and `StudyResource` expose the constrained field with a backward-compatible default. `GET /api/weeks/{week_id}/resources` returns `resource_type` and `classification_source`; sync discovery events also include the automatically inferred role.

Original Materials on the Week page provides a compact Lecture / Tutorial / Other selector. `PATCH /api/resources/{resource_id}/classification` accepts `{"resource_type":"lecture"}` (or `tutorial` / `other`) and saves the role with `classification_source=manual`. Errors leave the displayed role unchanged. Lecture and Tutorial retain their distinct colors; file links and parsing-health disclosure remain available.

The additive, idempotent startup migration defaults existing resources to `classification_source=automatic`. A manual change updates only the role and its source, preserving material timestamps and existing knowledge. Automatic sync writes have a database-level `classification_source != manual` condition, including when a sync session holds an older Resource object. Selecting any role explicitly makes it manual; no reset-to-automatic control is included in this targeted fix. Classification does not download, parse, generate knowledge or rebuild embeddings. The column is deferred on ORM reads so existing read-only retrieval experiment snapshots remain readable without migration.

V2.2 adds one nullable, deferred `classification_details` JSON column with version, method, confidence, reason, bounded metadata and merged evidence. It avoids changing the existing SQLite source CHECK constraint or rebuilding tables. Source remains automatic/manual; APIs additionally expose `classification_method` (metadata/document_content/llm/manual) and `classification_confidence`. Legacy automatic records return null until evaluated; manual records always expose method manual and confidence 1.0. Private metadata/reasons stay in the local database rather than the public response.

Historical experiment snapshots remain unchanged by manual edits. The current Course Q&A now reads live Resource metadata from the [shared course index](multi-course-indexing.md), so role-only edits are reflected without re-embedding. The existing source-safety checks still reject changed or stale source text.

## Validation and boundaries

Synthetic tests cover filenames, Page/Module context, conflict handling, migration preservation/idempotence, API serialization, direct/Page-linked sync, dry-run non-mutation and unchanged-file classification without reprocessing or knowledge invalidation. Frontend tests cover labels and original file links.

Old roles are not backfilled at startup. This classification phase does not redesign the interface or modify RAG, knowledge prompts, parsing or embedding pipelines. Synthetic tests cover scoring, fallback gating/bounds/schema/errors, manual ownership including concurrent writes, migration, CLI preview/apply and unchanged-file sync without reprocessing.
