# Phase 5.4 — AI Knowledge Extraction

Resource → stored DocumentChunks → current PDF warnings → temporary warning-aware input → KnowledgeService / AIService → provider → strict schema → provenance validation → item-level formula filtering → semantic support review → atomic persistence. Phase 6 now orchestrates this existing pipeline; see [Sync workflow](sync.md).

## Configuration

Local backend/.env is loaded; root .env, when present, overrides it. Process environment takes precedence. Never commit keys.

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-flash
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
KNOWLEDGE_OUTPUT_LANGUAGE=Chinese
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=6000
LLM_BATCH_CHARACTERS=12000
LLM_MAX_BATCHES=20
LLM_MAX_RETRIES=1
```

The factory selects OpenAI or DeepSeek without fallback/model rewriting. LLMProvider.generate(system, user, schema) -> str is unchanged. OpenAI uses Responses strict JSON Schema; DeepSeek uses Chat Completions JSON Output with disabled thinking. Empty/incomplete responses are errors. Keys, headers, prompts and response bodies are not logged. DeepSeek request_usage contains only numeric token counters/status/configured model, including responses later rejected by AIService; absent usage remains unknown.

## Provenance and evidence

Each input has [CHUNK_ID=<DocumentChunk.id> | PAGE=<page_number>], resource ID, chunk index, cleaned text and warning codes. The chunk ID is the database primary key, not its page number or resource-local index.

Concepts, key points, examples, exam focus and questions return source_chunk_ids and source_pages. Formulas return source_chunk_ids and their existing singular source_page. All input chunks must belong to one resource and have unique IDs before requests. Citations must reference actual chunks in the current batch; invented/duplicate IDs and mismatched page sets fail core validation. Evidence is derived from stored chunk content and contains source_chunk_id, page_number, quote and warnings. Optional legacy/debug model quotations are ignored, never persisted. Each item includes source_warnings.

Provider schema excludes evidence; enriched storage/response schemas include application evidence. OpenAI's all-properties-required strict JSON contract remains supported. JSON payload format changed; pre-5.3 knowledge requires regeneration, since fingerprints include pipeline version and chunk IDs. No new database columns/dependencies.

## Safety and optional filtering

Exam focus requires an explicit cue in actual cited source text: exam, assessment, quiz, important, remember, learning outcomes, or contextual academic test references. Generic technical test mentions and negated cues do not count. Missing cues or invalid optional exam citations remove the item and increment exam_focus_omitted / optional_items_omitted. A heading or bullet alone is insufficient.

Formula arrays remove outputs from unreliable sources and require reliable verbatim source text elsewhere. formulas_omitted counts removals. Formula IDs/pages remain validated. A conservative expression detector also checks concept names/definitions/explanations, key points, questions/answers, examples and exam focus; uncited topic/overview are discarded. Recognized expressions require whitespace-equivalent text in an independently reliable cited chunk. Merely occurring in a warned, unreadable or malformed source no longer suffices. Unrelated clean citations cannot justify an unsupported expression. The application never reconstructs mathematics. The deterministic checks are deliberately bounded heuristics, not a full mathematical parser.

Formula-related content failures remove only the affected item. Safe concept definitions/explanations survive with unsafe fields cleared; an unsafe name or no remaining definition/explanation drops the concept. Topic/overview are discarded before aggregation and derived from surviving reviewed content. Core provenance or schema failures still fail atomically. Other optional examples/exam-focus failures retain their existing filtering behavior. generated_counts counts candidate items from accepted batches before filtering/merge. Final lists may be smaller due to filtering, exact deduplication and the existing five-question cap.

These checks do not prove semantic entailment or detect all mathematics. Valid chunk IDs establish provenance, not truth. Ambiguous diagram labels, interleaved columns, unrelated exam cues and unsupported prose still need manual review. Existing Phase 4.1 parser/text/warnings remain unchanged; no layout reconstruction is attempted.

## Batching and persistence

Character budgets and batch limits are checked before requests. Oversized chunks are split only for prompts, retaining database identity and full original evidence. Validation/transient retries remain bounded with a safety reminder. No extra aggregation API call. Source fingerprint checks under a SQLite write lock reject source changes before persistence. A failed batch leaves previous knowledge intact.

One transaction upserts ResourceKnowledge, replaces that resource's Concepts/Questions, rebuilds its week's Summary and marks the Resource completed. Full citations/evidence/warnings/counts and knowledge are stored in JSON. Legacy Concept/Question page fields contain the first source page. GET reports stale sources.

## API and verification

- POST /api/resources/{id}/knowledge: explicit paid generation for one resource.
- GET /api/resources/{id}/knowledge: local read, no provider call.
- GET /health: works without credentials.

Run .venv/Scripts/python.exe -m pytest from backend. Tests use mock providers, temporary PDFs and isolated SQLite; no real API or local credentials are required. See the [public validation summary](validation-summary.md) for historical verification without private course content.


## Phase 5.2 semantic support

After provenance and existing safety checks, SemanticSupportService reviews generated claims using the same LLMProvider. Every review group contains only claims and their cited database chunk text, with the same temporary formula masking on warned pages as generation. Persisted/displayed evidence always contains the original stored text. Identical cited-source sets share source text within a request. No neighboring uncited chunks, external facts, retrieval, embeddings or web search are added. The reviewer is explicitly forbidden to borrow sources from another group in the same request.

Review covers concept name/definition/explanation separately, key points, examples, question answers (with their question as context), formula text/explanation, and retained exam focus. Responses use strict claim IDs, supported boolean, reason and unsupported_parts. Missing/duplicate/invented IDs, inconsistent decisions or invalid schema are processing failures with bounded retries. Ambiguous/partial support is unsupported. The service does not rewrite statements or add guessed citations.

Unsupported concepts/items are dropped. A supported concept definition can survive with its unsupported explanation removed (or vice versa). Unsupported formula explanations become null while a supported formula can remain. Topic and overview have no independent source citations, so they are composed deterministically from retained supported concept names/key points, without another generation call. No unsupported free-form summary is carried into persistence.

Each saved item has semantic_support assessments for retained text fields. ExtractionResult.semantic_review contains item counts (accepted unchanged, rejected, partially_reduced), batches and decision diagnostics. Rejection reasons are audit data, not learning content. Old results have no semantic_review and are stale under the new pipeline fingerprint; do not present them as semantically reviewed.

Requests are limited by the existing LLM_BATCH_CHARACTERS and LLM_MAX_BATCHES settings, separately for each stage, and at most 24 claims per semantic request. Complete claims/sources that cannot fit one request are conservatively omitted without truncation or a paid request. All semantic batches are planned before semantic calls. The existing retry limit applies to each batch; a processing failure preserves the previous database result.

ExtractionResult.request_counts separates generation and semantic_validation attempts (including retries). Usage retains only allowlisted returned counters tagged by stage. Missing token counts remain unknown. Semantic review increases API cost; one resource invocation can require several generation and review requests.

This is a model-based support assessment, not proof of truth. A reviewer can share the generator's mistakes, misread interleaved text, or miss an unsupported implication. No output is labeled a verified fact. Material claims and ambiguous math still warrant source review.

Historical automated/live results are summarized in the [public validation summary](validation-summary.md).


## Phase 5.3 warning-aware input and filtering diagnostics

`knowledge_input.py` creates temporary copies of chunks. Only pages carrying `suspicious_formula_layout` have obvious mathematical segments replaced with an explicit omission marker. IDs, pages, chunk indices and warnings remain unchanged. Ordinary hyphenated prose is retained. There is no formula repair, OCR, interpretation or change to raw text, cleaned text, DocumentChunks or the parser. The same masking applies to semantic-review source prompts. Detection is intentionally conservative: fragmented formulas may not be fully masked, so output formula guards and semantic review remain necessary.

`formula_filtered_counts` reports whole-item removals separately from `formula_reduced_counts` (concepts retained with unsafe fields cleared). `semantic_review.rejected_counts`, `reduced_counts` and `accepted_counts` report per-category outcomes after formula filtering and merge. Formula-array refusals include warned, non-verbatim and explicitly unreliable candidates. Other exam/provenance omissions still appear in the existing counters. These groups overlap with legacy diagnostic counters; do not sum legacy and new counters together.

`input_masking` reports masked source chunks/segments once, before batching. `generated_counts` counts schema/provenance-accepted generation attempts before filtering. Deduplication and the five-question cap can further reduce counts before semantic review. Reductions retain an item and therefore are not whole-item removals. Atomic save/reprocessing and bounded retry behavior are unchanged.

Detailed live findings remain local; see the [public validation summary](validation-summary.md).

## Phase 5.4 deterministic symbol fidelity — Phase 5 complete

`symbolic_safety.py` detects all Unicode private-use planes (category `Co`), U+FFFD and U+FFFC. Generation and semantic-review source prompts replace them with `[UNREADABLE_SYMBOL]`; original chunks, parsed text, PDFs and application evidence remain unchanged. The marker is protected from further formula masking. Generated fields containing unreadable characters/markers are omitted, never repaired.

Recognized arithmetic, powers, LaTeX, subscripts and Unicode operators are checked against reliable cited sources. Source reliability excludes formula/encoding/layout warnings, unreadable glyphs and incomplete equation chains such as `A = ... = B` (also Unicode ellipsis). A complete expression must match a reliable cited source with whitespace equivalence only. Unicode operators and signs introduced from unreadable sources require independent reliable source support. This closes the captured inferred-XOR and malformed-idle-equation cases without guessing their meanings. Normal prose still uses semantic support review; hyphenated prose and ordinary mentions of an equals-sign delimiter are not forced into verbatim matching.

The existing per-item/per-field filtering counters, schema/provenance checks, bounded retries, semantic review and atomic persistence are reused. No provider interface, database schema or dependencies changed. Pipeline fingerprints now include `phase5.4-symbolic-fidelity`; historical results are preserved and reported stale, not silently certified or rewritten.

The captured Phase 5.3 generation candidates were replayed through strict schema, provenance and the new deterministic safety checks; both known bad examples were blocked before an offline mock semantic reviewer. No paid call was necessary. Phase 5 final suite: 413 passed, 1 existing host symlink skip, 0 failed. See [public Phase 5 verification summary](validation-summary.md).

## Phase 6 integration

SyncService calls the existing KnowledgeService and provider factory without changing AI validation. Source fingerprints now also include `canvas_updated_at` so a successfully downloaded new Canvas revision invalidates old output even when extracted text happens to be identical. Default service/API reads exclude stale records with 404; `include_stale=true` explicitly retrieves history. Weekly Summary rebuilds include only current source fingerprints. Historical canonical JSON is retained.

An unchanged completed Resource is skipped even when its historical knowledge is stale: sync does not silently spend tokens repairing old results. Use explicit knowledge generation when regeneration is desired. A sync-created knowledge failure retains PDF/chunks and resumes the knowledge stage. KnowledgeService still rereads the PDF to validate warnings and source/chunk consistency; orchestration does not repeat the parse-and-replace-chunks stage. See [Phase 6 verification](sync.md).
