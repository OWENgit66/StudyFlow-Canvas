# RAG V0.4 — Local reranker experiment

Keep the V0.3 multilingual MiniLM retriever, its SQLite index, V0.2 hygiene,
original chunks, questions and reviewed pages unchanged. Use five candidates
per query: this isolates ordering, preserves the candidate set and bounds work
to 50 query–document pairs for the ten-question experiment. Top-5 hit rates
cannot change for a pure permutation; Top-1 and Top-3 still need evaluation.

## Model and execution

`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, official
`onnx/model_quint8_avx2.onnx` (approximately 119 MB). This multilingual MiniLMv2
cross-encoder was trained on mMARCO and supports the Chinese/English experiment.
It uses the installed FastEmbed/ONNX Runtime on CPU, two threads, one pair per
batch; no PyTorch dependency, remote inference or paid API.

Sources: [model card](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1),
[official quantized ONNX](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1/blob/main/onnx/model_quint8_avx2.onnx).

Before download, budget approximately 0.3 GB cache and 0.5–1 GB runtime RAM (an
estimate, not a measured peak). The cache is private under `data/reranker-models/`.
The default provider is offline. Explicitly preparing a public model is the only
operation allowed to enable downloads. No course text is uploaded.

The model returns raw cross-encoder logits, not calibrated confidence scores.
The wrapper keeps each original hit and its cosine score, adds rerank score and
original rank, and sorts only by descending rerank score. Ties keep the original
order. Invalid score counts, nonfinite scores, duplicate candidates and excessive
candidate counts fail explicitly; no hidden fallback or score blending occurs.
No production RetrievalService defaults or existing services are changed.

The model tokenizes query + full chunk text with a 512-token pair limit. Debug
records whether input truncation occurs. It neither alters DocumentChunk text nor
creates new chunks. None of the 50 pairs in this experiment exceeded the limit.

## Frozen evaluation

The runner opens V0.3's B index read-only, checks its model/version and corpus/index
hashes, and reuses production retrieval and the existing Eval functions. Before
reranking, all candidate IDs and cosine scores must match V0.3. Failure stops the
run; it does not tune retrieval or relabel Gold. Output directories cannot be
reused. Historical files and indexes are verified unchanged after the run.

From `backend`, with the model cache already prepared:

```powershell
.venv\Scripts\python.exe -m evals.rerank_eval --previous-dir ../data/retrieval-eval/rag-v0.3-multilingual --dataset ../data/retrieval-eval/questions.json --output-dir ../data/retrieval-eval/NEW_RERANK_EXPERIMENT
```

The frozen first experiment is in `data/retrieval-eval/rag-v0.4-reranker/`.
`comparison.json` retains before/after Top-5, original similarity, rerank score,
source IDs/pages, previews, truncation flags and all changed metrics.
`report.md` includes Q01/Q02/Q04/Q10 before/after detail. These private artifacts,
snapshots and caches stay Git-ignored.

| Metric | V0.3 B | V0.4 |
|---|---|---|
| Resource Hit@1 | 90% | 90% |
| Resource Hit@3 | 100% | 100% |
| Resource Hit@5 | 100% | 100% |
| Evidence Hit@1 | 30% | 90% |
| Evidence Hit@3 | 100% | 100% |
| Evidence Hit@5 | 100% | 100% |

There are no per-question Hit@K regressions on these ten questions. Q04/Q05/Q06/
Q08/Q09/Q10 improve Evidence Hit@1. Q01 still misses top-1 evidence. Q02 keeps a
valid evidence page first, although its former first page moves to rank 3; this is
not a claim that every individual relevant page improved rank. These small-set
results are not unseen accuracy, complete answer coverage or a production rollout.
No answer generation, API, UI, hybrid search or query transformations are added.
