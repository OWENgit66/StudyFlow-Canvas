# Evaluation: evidence before claims

Development used baselines, failure analysis and bounded experiments. Gold was reviewed against original stored content rather than generated from retrieval predictions. Private text, labels, screenshots and raw outputs remain outside the public repository; only aggregates and synthetic examples are published.

## Classification

| Stage | Correct / total | Interpretation |
|---|---:|---|
| V2.1 metadata baseline | 27/30 (90%) | Lecture 10/10, Tutorial 10/10, Other 7/10 |
| V2.2a conflict-handling regression | 30/30 (100%) | Same development/regression labels, not unseen accuracy |
| Independent holdout | Pending | No accuracy claim without labeled holdout samples |

The three errors were Other → Lecture: assignment/reading intent was overridden by weak Module/nearby “lecture” context. The minimal patch suppressed weak context when resource-purpose evidence conflicted, while preserving direct Lecture/Tutorial titles and useful Module context.

Later robust metadata/content/optional LLM fallback and manual overrides have automated coverage, but 30/30 is not measured accuracy for every later classifier path. Heuristic confidence is not a calibrated probability. Formats/commands: [backend/evals](../backend/evals/README.md). Current rules: [resource classification](resource-classification.md).

## Retrieval experiments

Ten frozen questions from one course were evaluated. Gold specifies an expected Resource and reviewed supporting pages. Model comparisons used the same 629 chunks, labels and candidate policy. This does not estimate generalization across courses/users.

| Stage | Resource @1 | @3 | @5 | Evidence @1 | @3 | @5 |
|---|---:|---:|---:|---:|---:|---:|
| V0 — Original semantic retrieval | 80% | 90% | 100% | Not measured | — | — |
| V0.1 — Evidence-level evaluation | 80% | 90% | 100% | 30% | 80% | 90% |
| V0.2 — Retrieval hygiene | 90% | 90% | 90% | 40% | 80% | 90% |
| V0.3 A — English BGE control | 90% | 90% | 90% | 40% | 80% | 90% |
| V0.3 B — Multilingual MiniLM | 90% | 100% | 100% | 30% | 100% | 100% |
| V0.4 — Multilingual + reranker | 90% | 100% | 100% | 90% | 100% | 100% |

Hit@K counts questions with a qualifying chunk in the first K chunks, not K deduplicated documents. Resource hit requires the expected resource; Evidence hit also requires a reviewed page. One hit need not cover every part of a multi-part question.

### V0 → V0.1: right document, wrong evidence

A definition question hit the expected PDF but retrieved an outline. Page-level Gold exposed the gap: Resource Hit@5 was 100%, Evidence Hit@5 only 90%. V0.1 changed evaluation, not retrieval.

### V0.2: preserve the regression

Narrow content-based cover/outline filtering removed distractions without a page-1 blanket rule. One question improved, but another lost its expected resource from Top-5: Resource Hit@5 fell to 90%. Further heuristics were not added to hide the regression.

### V0.3: isolate language mismatch

For Chinese questions over English slides, replace only `BAAI/bge-small-en-v1.5` with local multilingual MiniLM, retaining hygiene/cosine. Evidence Hit@3/5 rose to 100%, but Hit@1 fell to 30%. Q01/Q04 Top-1 regressed. Separate indexes preserved the English control; improved recall was not universally better ranking.

### V0.4: bounded reranking

The multilingual cross-encoder reranked five candidates per question: 50 query/document pairs. Evidence Hit@1 rose from 30% to 90%, with Hit@3/5 retained. No per-question Hit@K regression occurred in this set; Q01 still missed Top-1 evidence. Top-5 cannot improve merely by permuting the same five candidates.

This supported choosing multilingual retrieval plus reranking for Q&A. It does not establish unseen answer accuracy or production-scale performance.

## Answer and integration checks

Tests cover bounded context, source metadata, invalid/schema-mismatched JSON, nonexistent/duplicate citations, abstention, scope and provider errors. Shared-index tests cover incremental changes, version mismatch, readiness and source changes during generation.

Earlier single-query live checks verified answers and course-owned Sources, not strict sentence-level factuality. Adjacent evidence continuity was subsequently validated through a real browser Course Q&A smoke test on IDEA9106: the user confirmed that the missing intermediate Step 2 was answered, Sources belonged to the course, and no cross-course source was observed. This is user-confirmed smoke acceptance, not a new accuracy metric. No provider request, Retrieval Eval or embedding was run for this documentation pass.

## Latest regression verification

2026-10-07, Windows / Python 3.12 / Node.js 24:

| Check | Result |
|---|---|
| Full backend | 884 passed, 1 skipped, 0 failed |
| Frontend | 58 passed, 0 failed |
| ESLint | Passed |
| TypeScript | Passed |
| Next.js production build | Passed |

Tests use mocks/synthetic data and isolated databases. Test counts measure regression coverage, not answer quality; refresh them after implementation changes.

## Preserved experiment references

- [V0–V0.2 runner, storage and metrics](semantic-retrieval.md)
- [V0.3 profiles and A/B preservation](multilingual-retrieval-eval.md)
- [V0.4 reranker and candidate checks](local-reranker-eval.md)
- [V1 answer prototype / manual review format](rag-answer-prototype.md)

Snapshots, exact previews and private reports remain unchanged locally. Public examples show how to create a new independently labeled set; they cannot reproduce private-corpus metrics alone.
