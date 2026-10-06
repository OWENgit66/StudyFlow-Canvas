# Current RAG pipeline

```mermaid
flowchart LR
    Q[Question + course_id] --> Ready[Require complete compatible course index]
    Ready --> Embed[Local multilingual query embedding]
    Embed --> Candidates[Course-filtered cosine Top-5 + existing hygiene]
    Candidates --> Rerank[Local multilingual cross-encoder]
    Rerank --> Context[Top-3 / bounded context, at most 5]
    Context --> Check[Validate live source identity]
    Check --> LLM[LLMProvider: grounded JSON answer]
    LLM --> Validate[Schema + citation validation + source recheck]
    Validate --> UI[Answer + source/page links]
```

## Retrieval

- Live runtime selects `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` and `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, both on CPU from local caches.
- SQL joins restrict candidates to the requested course. Resource type is optional; Other is not excluded by default.
- Only compatible vectors qualify. Existing hygiene excludes narrowly identified covers/outlines, without excluding every first page.
- Cosine returns five candidates; the cross-encoder reorders them. Its score is not calibrated confidence.
- Optional Week filtering occurs after reranking the course Top-5; it can underfill rather than broaden candidate retrieval.

## Answer context

RAGAnswerService defaults to three reranked items. The answer-only selector reduces domination by unanswered exercises and can include adjacent explanatory text. It does not modify retrieval ranks or Gold evaluation.

Continuity can bridge one or two missing pages between selected original anchors from the same course/resource when normalized section headings match and relate to the question. Existing chunks undergo ownership/usability checks; obvious low-information/unanswered-exercise candidates are rejected. No recursive expansion occurs. Context stays within five chunks and 30,000 serialized characters.

This is conservative text matching, not general section understanding. Ask neither parses PDFs nor indexes documents. See [limitations](limitations.md).

## Generation and citations

The prompt asks for supplied-evidence-only answers, in the question's language, using plain text/simple numbering and inline citation IDs. Missing evidence requires abstention; damaged formulas must not be reconstructed.

Pydantic validates provider JSON. Citation IDs must be unique, match inline references and belong to supplied evidence. The server copies title, page, course and source URL from actual evidence. The live adapter rechecks readiness and source identity before/after generation instead of silently using a stale snapshot.

These checks prevent fabricated source identities, not every unsupported interpretation. Strict sentence-level grounding remains a limitation.

## Entry points

- `POST /api/courses/{course_id}/ask`: question, optional week_id/resource_type; existing answer/sources schema.
- `GET /api/courses/{course_id}/index-status`: ready, indexing, stale, unavailable or error.
- Course UI: one question → one answer, loading/errors and source links. No conversation history, memory or streaming.
- Historical runners under `backend/evals/` retain frozen experimental snapshots; they are distinct from the live shared-index UI path.

See [evaluation](evaluation.md) for frozen results and [multi-course indexing](multi-course-indexing.md) for maintenance commands.
