# StudyFlow scope and roadmap

This is the current capability map. Phase numbering in AGENTS.md and historical records describes the intended sequence; later explicitly scoped tasks delivered text RAG before visual/multimodal features.

| Capability | Status |
|---|---|
| V1 Canvas → PDF → structured knowledge → learning UI | Complete / stable foundation |
| Resource roles and metadata conflict handling | Implemented; small regression set documented |
| Existing-content / optional LLM classification fallback | Implemented with bounded maintenance calls |
| Manual classification override | Implemented; sync must not overwrite it |
| Multilingual embedding + local reranker | Implemented; frozen V0–V0.4 experiments preserved |
| Course Q&A API and single-answer UI | Implemented with validated source metadata |
| Multi-course shared index / existing-course backfill | Implemented and locally verified |
| Adjacent continuity / plain-text answer prompt | Implemented; tests/local preview passed; subsequent real browser IDEA9106 Q&A smoke validated by the user |
| Independent classification holdout | Infrastructure available; labeling/evaluation pending |
| DocumentPage screenshots / multimodal RAG | Deferred; not implemented |
| Separate Lecture/Tutorial knowledge-generation pipelines | Deferred; not implemented |

No feature is scheduled by this documentation update. New work requires a separate scoped request. Incomplete acceptance and operational boundaries are in [limitations](limitations.md); measured results are in [evaluation](evaluation.md).
