# RAG V0.3 — Multilingual Embedding A/B

This experiment changes the embedding model while reusing the production provider,
RetrievalService, V0.2 hygiene, cosine/Top-K logic and V0.1 Eval unchanged. It does
not generate answers or change the default production model.

- A: `BAAI/bge-small-en-v1.5`, existing 384-dimensional index.
- B: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions,
  FastEmbed's supported quantized ONNX distribution. Its parallel multilingual
  training includes Chinese and English; this makes it a candidate for Chinese
  questions against English documents, not a guarantee of better retrieval.

References: [Sentence Transformers multilingual models](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html),
[FastEmbed's ONNX distribution](https://huggingface.co/Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q).

The installed FastEmbed lists about 0.22 GB for B. Allow approximately 0.5 GB for
the download/cache and an estimated 1–2 GB additional CPU inference RAM; this is
a planning estimate, not a measured peak. Both models execute locally. The only
network operation is an explicit public-model download, never document upload.

## Index isolation

The production `chunk_embeddings` table remains unchanged. For this bounded
experiment, model/version isolation is physical: each arm has its own SQLite
file, named with a hash of model + version, and a profile JSON identifying model,
version, dimension, course and index digest. Each row still records model/version
and existing content/source hashes. Production retrieval validates those fields.

The runner copies only the selected course's Semester, Course, Week, Resource and
DocumentChunk rows. A additionally copies the existing embeddings; B starts with
an empty **new** index. B is copied from A's source snapshot, so both arms use
exactly the same corpus/metadata. Neither the live index nor A's vectors are
overwritten. There is no production migration. These are private experiment
snapshots, including a deliberate duplicate of the small frozen source corpus,
not a new production multi-model database design.

Reusing an output directory or snapshot file is rejected. Missing/stale A vectors
stop the experiment rather than silently re-embedding A. There is no automatic
model download or fallback. An interrupted experiment's files are retained for
inspection; the runner does not silently overwrite/restart it.

## Frozen variables and model-dependent details

Keep questions, expected resources/pages, course, text, source metadata, hygiene,
retrieval and Eval code fixed. The runner checks hashes and compares each question
at all six metrics; it lists regressions as well as improvements.

Tokenization and the model's input limits are part of the model package. The
unchanged provider computes temporary windows as `min(480, tokenizer_limit-32)`:
the installed A uses 480 tokens; B uses 96. Both use the same existing weighted
window pooling implementation without changing stored chunks or discarding their
tails. Thus this compares complete supported embedding configurations, not an
isolated causal test of multilingual training alone. B index batches are limited
to four chunks for RAM control; this does not change the per-input encoding logic.

## Run once with prepared local caches

From `backend`, after explicitly preparing B's public model cache:

```powershell
.venv\Scripts\python.exe -m evals.retrieval_ab --course-id COURSE_ID --dataset ../data/retrieval-eval/questions.json --output-dir ../data/retrieval-eval/NEW_EXPERIMENT_DIRECTORY
```

Choose a new directory for every explicitly authorized experiment. The frozen
V0.3 run uses `data/retrieval-eval/rag-v0.3-multilingual/`. Outputs include two
SQLite indexes, model profiles, A/B results and `comparison.json`. Raw previews,
Gold, snapshots, caches and historical reports remain Git-ignored private data.
The previous V0, V0.1 and V0.2 files are not overwritten.

Synthetic tests in `backend/tests/test_retrieval_ab.py` cover separate index
contents, preservation of A/live data, course isolation, identical source rows,
foreign keys, overwrite refusal, and transparent regression reporting. They do
not require a model download or any private corpus.

## Frozen first result

Both arms used the same 629 chunks and 10 questions with unchanged V0.2 hygiene.
A reproduced the V0.2 rankings/scores. B generated 629 new vectors in its own
SQLite file. Each arm computed 10 local query embeddings; no paid API was used.

| Metric | A: English BGE | B: multilingual MiniLM |
|---|---|---|
| Resource Hit@1 | 90% | 90% |
| Resource Hit@3 | 90% | 100% |
| Resource Hit@5 | 90% | 100% |
| Evidence Hit@1 | 40% | 30% |
| Evidence Hit@3 | 80% | 100% |
| Evidence Hit@5 | 90% | 100% |

Q02's reviewed evidence reached B rank 1; Q10 Evidence Hit@3 also improved.
Regressions: Q01 Resource/Evidence Hit@1 and Q04 Evidence Hit@1 changed from hit
to miss. No additional heuristics or model changes were made after this run.
This supports improved top-3/top-5 coverage on this small set, not an overall
win or a default-model switch. The two models' cosine magnitudes should not be
treated as directly comparable confidence scores. See the private experiment's
`report.md` for Q02's exact Top-5 and the per-question comparison.
