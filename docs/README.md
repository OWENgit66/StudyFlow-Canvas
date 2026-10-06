# Documentation map

The README is the short project introduction. These guides describe the current system:

| Guide | Purpose |
|---|---|
| [Architecture](architecture.md) | Data flow, service boundaries and persistence |
| [Resource classification](resource-classification.md) | Scoring, bounded fallback and manual precedence |
| [RAG pipeline](rag-pipeline.md) | Retrieval → context → answer → citation |
| [Evaluation](evaluation.md) | Frozen experiments, regressions and measurement limits |
| [Multi-course indexing](multi-course-indexing.md) | Incremental identity, readiness, sync hook and backfill |
| [Limitations](limitations.md) | Grounding, documents, operations and reproducibility |

## Operational reference

[Canvas](canvas.md), [active-semester sync](active-semester-sync.md), [Page-linked materials](page-materials.md), [material storage](material-storage.md), [database](database.md), [document parsing](documents.md), [parsing health](parsing-health.md), [structured knowledge](ai-knowledge.md), [sync](sync.md), [interface](interface.md), [Windows launcher](windows-launcher.md).

These retain detailed setup/API behavior so the introductory README does not duplicate it. The [roadmap](roadmap.md) records current scope.

## Historical records

The earlier [readiness audit](rag-plan.md), [V0–V0.2 retrieval](semantic-retrieval.md), [V0.3 multilingual experiment](multilingual-retrieval-eval.md), [V0.4 reranker experiment](local-reranker-eval.md) and [V1 answer prototype](rag-answer-prototype.md) retain implementation rationale, commands and stage-specific results. Their “not implemented” statements and test counts describe that historical stage, not today's product.

Phase verification files, [V1 release](v1-release.md) and [validation summary](validation-summary.md) remain historical evidence. Nothing was deleted or moved during this documentation pass. Private live reports/screenshots stay Git-ignored; local private paths in older records are not public downloadable artifacts.
